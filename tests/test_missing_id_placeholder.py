"""A source without an ``id`` placeholder raises ``MissingIdPlaceholderError`` wherever it is detected."""

import pickle

import pandas as pd
import pytest

from id_translation import Translator
from id_translation.exceptions import MissingIdPlaceholderError
from id_translation.fetching import AbstractFetcher, CacheAccess, MemoryFetcher, PandasFetcher
from id_translation.fetching.exceptions import UnknownIdPlaceholderError, UnknownPlaceholderError
from id_translation.fetching.types import IdsToFetch, PartialCacheHit
from id_translation.mapping import Mapper
from id_translation.offline import TranslationMap
from id_translation.offline.types import PlaceholderTranslations

NO_ID = {"animals": {"code": [1, 2], "name": ["cat", "dog"]}}
CALLER: MemoryFetcher[str, int] = MemoryFetcher({"s": {"id": [1]}})


class TestInline:
    @pytest.mark.parametrize("fmt", [None, "{name}"])
    def test_translator_raises_at_construction(self, fmt):
        # With a fmt that doesn't use {id}, this used to key the map by the last column and fail every ID silently.
        kwargs = {} if fmt is None else {"fmt": fmt}
        with pytest.raises(MissingIdPlaceholderError, match=r"Source 'animals' has no 'id' placeholder") as exc_info:
            Translator(NO_ID, **kwargs)

        exc = exc_info.value
        assert type(exc) is MissingIdPlaceholderError
        assert exc.source == "animals"
        assert exc.placeholders == ("code", "name")
        assert exc.__notes__ == [
            "Hint: Inline data and plain Fetcher results are not mapped; the ID column must be named 'id'.",
            "Hint: To map another column, use a MemoryFetcher with an override: Mapper(overrides={'id': '<column>'}).",
        ]

    def test_translation_map_raises_at_construction(self):
        pht = PlaceholderTranslations.make("animals", NO_ID["animals"])
        with pytest.raises(MissingIdPlaceholderError):
            TranslationMap({"animals": pht})

    def test_id_column_anywhere(self):
        data = {"animals": {"name": ["cat", "dog"], "id": [1, 2], "legs": [4, 4]}}
        translator: Translator[str, str, int] = Translator(data, fmt="{name}")
        assert translator.translate([1, 2], names="animals") == ["cat", "dog"]


class TestFetchers:
    def test_memory_fetcher_override_maps_id(self):
        translator: Translator[str, str, int] = Translator(
            MemoryFetcher(NO_ID, mapper=Mapper(overrides={"id": "code"}))
        )
        assert translator.translate([1, 2], names="animals") == ["1:cat", "2:dog"]

    def test_source_without_placeholders(self):
        fetcher: MemoryFetcher[str, int] = MemoryFetcher({"s": PlaceholderTranslations("s", (), [])})
        with pytest.raises(UnknownIdPlaceholderError):
            fetcher.initialize_sources()

    def test_checked_at_discovery(self):
        class Fetcher(AbstractFetcher[str, int]):
            def _initialize_sources(self, task_id):  # noqa: ARG002
                return {"people": ["id", "name"], "orders": ["order_no", "amount"]}

            def fetch_translations(self, instr):  # noqa: ARG002  # pragma: no cover
                raise AssertionError

        fetcher = Fetcher(mapper=Mapper("equality"))
        with pytest.raises(UnknownIdPlaceholderError) as exc_info:
            fetcher.initialize_sources()

        assert exc_info.value.source == "orders"
        with pytest.raises(UnknownIdPlaceholderError):
            fetcher.initialize_sources()  # Still uninitialized.

    def test_pandas_fetcher_checked_at_discovery(self, tmp_path):
        pd.DataFrame({"id": [1], "name": ["Ada"]}).to_csv(tmp_path / "people.csv", index=False)
        pd.DataFrame({"order_no": [7]}).to_csv(tmp_path / "orders.csv", index=False)

        fetcher: PandasFetcher[int] = PandasFetcher(read_path_format=str(tmp_path / "{}.csv"))
        with pytest.raises(UnknownIdPlaceholderError, match="source='orders'"):
            fetcher.initialize_sources()

    def test_discovery_maps_id_once_per_source(self):
        class Counting(MemoryFetcher[str, int]):
            calls: list[str] = []

            def map_placeholders(self, source, placeholders, **kwargs):
                self.calls.append(source)
                return super().map_placeholders(source, placeholders, **kwargs)

        fetcher = Counting({"a": {"id": [1]}, "b": {"id": [2]}})
        fetcher.initialize_sources()
        assert sorted(fetcher.calls) == ["a", "b"]

    def test_cache_blamed_for_its_own_rows(self):
        class Fetcher(AbstractFetcher[str, int]):
            def _initialize_sources(self, task_id):  # noqa: ARG002
                return {"animals": ["id", "name"]}

            def fetch_translations(self, instr):  # noqa: ARG002  # pragma: no cover
                raise AssertionError("should be served from the cache")

        class Cache(CacheAccess[str, int]):
            def load(self, instr):  # noqa: ARG002
                return PlaceholderTranslations("animals", ("name",), [("cat",)])

            def store(self, instr, translations):  # noqa: ARG002  # pragma: no cover
                raise AssertionError

        with pytest.raises(UnknownIdPlaceholderError) as exc_info:
            Fetcher(cache_access=Cache()).fetch([IdsToFetch("animals", {1})])
        assert "Hint: The source has ['id'], but CacheAccess.load() did not return them." in exc_info.value.__notes__

    def test_id_column_validates_override_target(self):
        fetcher: MemoryFetcher[str, int] = MemoryFetcher(NO_ID, mapper=Mapper(overrides={"id": "nope"}))

        with pytest.raises(UnknownIdPlaceholderError) as exc_info:
            fetcher.id_column("animals", candidates=["code", "name"])
        assert exc_info.value.missing_placeholders == ("nope",)

    @pytest.mark.parametrize(
        "load",
        [None, PartialCacheHit(PlaceholderTranslations("animals", ("id", "name"), [(1, "cat")]))],
        ids=["miss", "partial-hit"],
    )
    def test_checked_before_store(self, load):
        # A cache must never be handed rows without the ID column, including the complement of a partial hit.
        class DropsId(AbstractFetcher[str, int]):
            def _initialize_sources(self, task_id):  # noqa: ARG002
                return {"animals": ["id", "name"]}

            def fetch_translations(self, instr):  # noqa: ARG002
                return PlaceholderTranslations("animals", ("name",), [("dog",)])

        class RecordingCache(CacheAccess[str, int]):
            def __init__(self) -> None:
                super().__init__()
                self.stored: list[PlaceholderTranslations[str]] = []

            def load(self, instr):  # noqa: ARG002
                return load

            def store(self, instr, translations):  # noqa: ARG002
                self.stored.append(translations)

        cache = RecordingCache()
        fetcher = DropsId(cache_access=cache)

        with pytest.raises(UnknownIdPlaceholderError) as exc_info:
            fetcher.fetch([IdsToFetch("animals", {1, 2})])
        assert cache.stored == []
        assert "Hint: The source has ['id'], but fetch_translations() did not return them." in exc_info.value.__notes__

    def test_renamed_id_column_not_returned(self):
        class DropsUserId(AbstractFetcher[str, int]):
            def _initialize_sources(self, task_id):  # noqa: ARG002
                return {"users": ["user_id", "name"]}

            def fetch_translations(self, instr):  # noqa: ARG002
                return PlaceholderTranslations("users", ("name",), [("Fred",)])

        fetcher = DropsUserId(mapper=Mapper(overrides={"id": "user_id"}))
        with pytest.raises(UnknownIdPlaceholderError) as exc_info:
            fetcher.fetch([IdsToFetch("users", {1})])
        hint = "Hint: The source has ['user_id'], but fetch_translations() did not return them."
        assert exc_info.value.__notes__ == [hint]


class TestShadowedIdColumn:
    """An override ``id -> code`` wins over a literal ``id`` column that a fetcher returns anyway."""

    DATA = {"s": {"id": [1, 2], "code": [2, 1], "name": ["one", "two"]}}

    @pytest.mark.parametrize("return_all", [False, True])
    def test_memory_fetcher(self, return_all):
        fetcher: MemoryFetcher[str, int] = MemoryFetcher(
            self.DATA, return_all=return_all, mapper=Mapper(overrides={"id": "code"})
        )
        translator: Translator[str, str, int] = Translator(fetcher)
        assert translator.translate([1], names="s") == ["1:two"]

    def test_pandas_fetcher(self, tmp_path):
        pd.DataFrame(self.DATA["s"]).to_csv(tmp_path / "s.csv", index=False)
        fetcher: PandasFetcher[int] = PandasFetcher(str(tmp_path / "{}.csv"), mapper=Mapper(overrides={"id": "code"}))
        translator: Translator[str, str, int] = Translator(fetcher)
        assert translator.translate([1], names="s") == ["1:two"]


class TestHierarchy:
    @pytest.mark.parametrize(
        ("unknown", "expected_type"),
        [
            ("id", UnknownIdPlaceholderError),
            (["id", "legs"], UnknownIdPlaceholderError),
            ("legs", UnknownPlaceholderError),
        ],
    )
    def test_factory_picks_type(self, unknown, expected_type):
        exc = UnknownPlaceholderError.for_placeholders(unknown, placeholders=["name"], source="s", caller=CALLER)
        assert type(exc) is expected_type

    @pytest.mark.parametrize(
        "make",
        [
            lambda: Translator(NO_ID),
            lambda: Translator[str, str, int](MemoryFetcher(NO_ID)).translate([1], names="animals"),
            lambda: MemoryFetcher(NO_ID, mapper=Mapper(overrides={"id": "nope"})).initialize_sources(),
        ],
        ids=["inline", "unmapped", "bad-override"],
    )
    @pytest.mark.parametrize("catch", [MissingIdPlaceholderError, ValueError])
    def test_one_type_catches_every_path(self, make, catch):
        with pytest.raises(catch):
            make()

    def test_subclass_keeps_its_attributes(self):
        # MissingIdPlaceholderError.__init__ runs inside UnknownPlaceholderError's super() chain with default arguments.
        exc = UnknownPlaceholderError.for_placeholders(
            "id", placeholders=["name"], source="s", caller=CALLER, hints="h"
        )

        assert isinstance(exc, MissingIdPlaceholderError)
        assert isinstance(exc, RuntimeError)
        assert (exc.source, exc.placeholders, exc.missing_placeholders) == ("s", ("name",), ("id",))
        assert exc.__notes__ == ["Hint: h"]

        clone = pickle.loads(pickle.dumps(exc))  # noqa: S301
        assert clone.__dict__ == exc.__dict__
