"""Tests for fetcher-provided transformers; see ``Fetcher.get_transformer``."""

import threading
import warnings
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from id_translation import Translator
from id_translation.exceptions import TranslationWarning
from id_translation.fetching import MemoryFetcher, MultiFetcher
from id_translation.transform import TransformerStack
from id_translation.transform.types import Transformer

from .conftest import DATA, Marker, translate

TWO_SOURCES = {
    "bitmasks": {"id": [1, 2], "name": ["one", "two"]},
    "plain": {"id": [1], "name": ["just-one"]},
}


class ProvidingFetcher(MemoryFetcher[str, int]):
    """MemoryFetcher which provides transformers for its sources, recording every query."""

    def __init__(self, data: Mapping[str, Any], provide: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__(data, **kwargs)
        self.provide = dict(provide or {})
        self.queries: list[str] = []

    def get_transformer(self, source: str) -> Transformer[int] | Sequence[Transformer[int]] | None:
        self.queries.append(source)
        return self.provide.get(source)


class Locked(Marker):
    """Not picklable and not deep-copyable; only reached while copying state."""

    def __init__(self) -> None:
        super().__init__("locked")
        self.lock = threading.Lock()


class LockedProvider(MemoryFetcher[str, int]):
    """Provides an unpicklable transformer, but is picklable itself: the answer is built on demand."""

    def get_transformer(self, source: str) -> Transformer[int] | None:
        return Locked() if source == "bitmasks" else None


def test_default_is_none():
    fetcher = MemoryFetcher[str, int](DATA)
    assert fetcher.get_transformer("bitmasks") is None

    translator = Translator[str, str, int](fetcher).initialize_sources()
    assert translator._tx._transformers == {}


def test_provided_transformer_is_applied():
    fetcher = ProvidingFetcher(TWO_SOURCES, {"bitmasks": Marker("fetcher")})
    translator = Translator[str, str, int](fetcher)

    assert translate(translator) == "1:one|fetcher"
    assert translator._tx._transformers.keys() == {"bitmasks"}, (
        "sources without a provided transformer must be untouched"
    )
    assert translator.translate((1,), names="plain") == ("1:just-one",)


def test_chain_becomes_a_stack():
    first, second = Marker("first"), Marker("second")
    fetcher = ProvidingFetcher(DATA, {"bitmasks": [first, second]})
    translator = Translator[str, str, int](fetcher).initialize_sources()

    stack = translator._tx._transformers["bitmasks"]
    assert isinstance(stack, TransformerStack)
    assert stack.transformers == (first, second), "members must keep the given order"
    assert translate(translator) == "1:one|first|second"


def test_offline_translator_is_not_queried():
    translator = Translator[str, str, int]({"bitmasks": {1: "one"}}).initialize_sources()
    assert translator._tx._transformers == {}


def test_transformers_view_is_read_only():
    translator = Translator[str, str, int](ProvidingFetcher(DATA, {"bitmasks": Marker("fetcher")}))
    translator.initialize_sources(settle_transformers=True)

    with pytest.raises(TypeError):
        translator.transformers["bitmasks"] = Marker("sneaky")  # type: ignore[index]


class TestQueriedOnce:
    @pytest.fixture
    def fetcher(self) -> ProvidingFetcher:
        return ProvidingFetcher(TWO_SOURCES, {"bitmasks": Marker("fetcher")})

    @pytest.fixture
    def translator(self, fetcher: ProvidingFetcher) -> Translator[str, str, int]:
        return Translator(fetcher)

    def test_queried_once_per_source(self, translator, fetcher):
        translate(translator)
        translate(translator)

        assert Counter(fetcher.queries) == {"bitmasks": 1, "plain": 1}

    def test_repeated_initialize_sources(self, translator, fetcher):
        for _ in range(3):
            translator.initialize_sources()

        assert Counter(fetcher.queries) == {"bitmasks": 1, "plain": 1}


class TestOverlap:
    """A fetcher describes the source it serves, so its transformer chains ahead of anything declared for it."""

    def test_declared_and_provided_chain_fetcher_first(self):
        fetcher = ProvidingFetcher(TWO_SOURCES, {"bitmasks": Marker("fetcher")})
        translator = Translator[str, str, int](fetcher, transformers={"bitmasks": Marker("declared")})

        assert translate(translator) == "1:one|fetcher|declared", "the fetcher's runs first, as aux files do"

    def test_partially_overlapping_chain_repeats_the_shared_member(self):
        shared = Marker("shared")
        fetcher = ProvidingFetcher(TWO_SOURCES, {"bitmasks": [shared, Marker("extra")]})
        translator = Translator[str, str, int](fetcher, transformers={"bitmasks": shared})

        with pytest.warns(TranslationWarning, match="Duplicate transformer"):
            assert translate(translator) == "1:one|shared|extra|shared"

    def test_provided_is_applied_twice_when_also_declared(self):
        provided = Marker("fetcher")
        fetcher = ProvidingFetcher(TWO_SOURCES, {"bitmasks": provided})
        translator = Translator[str, str, int](fetcher, transformers={"bitmasks": provided})

        with pytest.warns(TranslationWarning, match="Duplicate transformer") as record:
            assert translate(translator) == "1:one|fetcher|fetcher"

        message = str(record[0].message)
        assert "source='bitmasks'" in message, "a member's default repr does not say which source to fix"
        assert "provided by fetcher=ProvidingFetcher" in message
        assert "registered on the Translator" in message

    def test_duplicate_from_a_multi_fetcher_names_the_child(self):
        provided = Marker("fetcher")
        fetcher = MultiFetcher(
            ProvidingFetcher(TWO_SOURCES, {"bitmasks": provided}), MemoryFetcher({"other": DATA["bitmasks"]})
        )
        translator = Translator[str, str, int](fetcher, transformers={"bitmasks": provided})

        with pytest.warns(TranslationWarning, match="Duplicate transformer") as record:
            translate(translator)

        message = str(record[0].message)
        assert "provided by rank-0 fetcher ProvidingFetcher" in message, "the child that serves the source"
        assert "MemoryFetcher" not in message, "not a dump of every child"

    def test_duplicate_from_a_nested_multi_fetcher_names_the_leaf(self):
        provided = Marker("fetcher")
        inner = MultiFetcher(
            ProvidingFetcher(TWO_SOURCES, {"bitmasks": provided}), MemoryFetcher({"a": DATA["bitmasks"]})
        )
        fetcher = MultiFetcher(MemoryFetcher({"b": DATA["bitmasks"]}), inner)  # The leaf is rank 0 in rank-1 `inner`.
        translator = Translator[str, str, int](fetcher, transformers={"bitmasks": provided})

        with pytest.warns(TranslationWarning, match="Duplicate transformer") as record:
            translate(translator)

        message = str(record[0].message)
        assert "fetcher=ProvidingFetcher" in message
        assert "rank-" not in message, "a rank within `inner` would read as one within `fetcher`"
        assert "MemoryFetcher" not in message, "not a dump of every grandchild"

    def test_duplicate_names_the_file_of_a_lone_fetcher(self):
        provided = Marker("fetcher")
        fetcher = ProvidingFetcher(TWO_SOURCES, {"bitmasks": provided}, identifiers=["fetcher.toml"])
        translator = Translator[str, str, int](fetcher, transformers={"bitmasks": provided})

        with pytest.warns(TranslationWarning, match="Duplicate transformer") as record:
            translate(translator)

        assert "(file='fetcher.toml')" in str(record[0].message)

    def test_configured_non_transformer_raises(self):
        fetcher = ProvidingFetcher(TWO_SOURCES, {"bitmasks": Marker("fetcher")})
        fetcher._transform_config = {"bitmasks": [42]}  # type: ignore[list-item]

        with pytest.raises(TypeError, match="Element 1 of the transformer chain"):
            Translator[str, str, int](fetcher).initialize_sources()

    def test_provided_and_configured_names_source_and_fetcher(self):
        """The `[fetching.transform]` section of the fetcher's own file repeats what `get_transformer()` provides."""
        provided = Marker("fetcher")
        fetcher = ProvidingFetcher(TWO_SOURCES, {"bitmasks": provided})
        fetcher._transform_config = {"bitmasks": [provided]}

        with pytest.warns(TranslationWarning, match="Duplicate transformer") as record:
            assert translate(Translator[str, str, int](fetcher)) == "1:one|fetcher|fetcher"

        assert "for source='bitmasks' from fetcher=ProvidingFetcher" in str(record[0].message)

    @pytest.fixture
    def fetcher(self) -> ProvidingFetcher:
        return ProvidingFetcher(TWO_SOURCES, {"bitmasks": Marker("fetcher")})

    def test_query_then_explicit_raises(self, fetcher):
        translator = Translator[str, str, int](fetcher).initialize_sources(settle_transformers=False)

        with pytest.raises(ValueError, match="already registered"):
            translator.register_transformer("bitmasks", Marker("explicit"))

    def test_append_chains_onto_provided(self, fetcher):
        translator = Translator[str, str, int](fetcher).initialize_sources(settle_transformers=False)
        translator.register_transformer("bitmasks", Marker("explicit"), on_existing="append")

        assert translate(translator) == "1:one|fetcher|explicit", "the provided transformer runs first"

    def test_overwrite_replaces_provided(self, fetcher):
        translator = Translator[str, str, int](fetcher).initialize_sources(settle_transformers=False)
        translator.register_transformer("bitmasks", Marker("explicit"), on_existing="overwrite")

        assert translate(translator) == "1:one|explicit"

    def test_bad_value_raises_with_notes(self):
        """Not a conflict -- there is no prior registration -- so the conflict-specific hint must not appear."""
        fetcher = ProvidingFetcher(DATA, {"bitmasks": 42})
        translator = Translator[str, str, int](fetcher)

        with pytest.raises(TypeError, match="must implement the Transformer protocol") as info:
            translator.initialize_sources()

        notes = "\n".join(info.value.__notes__)
        assert "get_transformer" in notes, "the query that produced the bad value must be identifiable"
        assert "already has a registration" not in notes, "nothing was registered; this source has no such thing"

    def test_arbitrary_exception_rolls_back(self):
        """Not just TypeError/ValueError: a duplicate chain warns, and `-W error` makes that a TranslationWarning."""
        duplicate = Marker("duplicate")
        fetcher = ProvidingFetcher(TWO_SOURCES, {"bitmasks": Marker("fetcher"), "plain": [duplicate, duplicate]})
        translator = Translator[str, str, int](fetcher)

        with warnings.catch_warnings(), pytest.raises(TranslationWarning, match="Duplicate transformer"):
            warnings.simplefilter("error", TranslationWarning)
            translator.initialize_sources()

        assert translator._tx._transformers == {}, "'bitmasks' must not survive the failed pass"


class TestRetention:
    """Provided transformers behave like any registration once applied; see also test_registration.TestRetention."""

    @pytest.fixture
    def fetcher(self) -> ProvidingFetcher:
        return ProvidingFetcher(DATA, {"bitmasks": Marker("fetcher")})

    @pytest.fixture
    def translator(self, fetcher: ProvidingFetcher) -> Translator[str, str, int]:
        return Translator(fetcher)

    def test_copy_after_query_does_not_requery(self, translator):
        """Derived results travel with the copy; a second pass over the same fetcher would self-conflict."""
        translate(translator)
        copy = translator.copy()

        assert translate(copy) == "1:one|fetcher", "applied exactly once"
        assert isinstance(copy.fetcher, ProvidingFetcher)
        assert Counter(copy.fetcher.queries) == {"bitmasks": 1}, "inherited from the original; no new queries"

    def test_copy_reusing_the_same_fetcher_does_not_requery(self, translator):
        """`fetcher='keep'` is what the failed-deepcopy hint tells users to do; it is not a new source."""
        translate(translator)
        copy = translator.copy(fetcher="keep")

        assert copy.fetcher is translator.fetcher
        assert translate(copy) == "1:one|fetcher", "applied exactly once"
        assert Counter(copy.fetcher.queries) == {"bitmasks": 1}, "same fetcher: no new queries"

    @pytest.mark.parametrize("queried_first", [False, True])
    def test_copy_transformers_override_does_not_depend_on_timing(self, queried_first):
        fetcher = ProvidingFetcher(TWO_SOURCES, {"bitmasks": Marker("fetcher"), "plain": Marker("fetcher")})
        translator = Translator[str, str, int](fetcher)
        if queried_first:
            translate(translator)

        explicit = Marker("explicit")
        copy = translator.copy(transformers={"bitmasks": explicit})

        assert copy._tx._transformers == {"bitmasks": explicit}, "the override is the complete set"
        assert translate(copy) == "1:one|explicit"
        assert copy.translate((1,), names="plain") == ("1:just-one",), "not re-derived for unnamed sources either"

    def test_copy_before_query_queries_later(self, translator, fetcher):
        copy = translator.copy()

        assert translate(copy) == "1:one|fetcher"
        assert fetcher.queries == [], "the original must not be affected by the copy"
        assert translate(translator) == "1:one|fetcher"

    def test_copy_rejects_fetcher_override(self, translator):
        with pytest.raises(TypeError, match="FetcherCopyMode"):
            translator.copy(fetcher=ProvidingFetcher(TWO_SOURCES, {"plain": Marker("B")}))

    def test_copy_with_none_transformers_starts_over(self, translator):
        translate(translator)

        copy = translator.copy(transformers=None)
        assert copy._tx._transformers == {}
        assert translate(copy) == "1:one|fetcher", "re-derived from the (copied) fetcher"

    def test_go_offline(self, translator):
        translator.go_offline()
        assert translate(translator) == "1:one|fetcher"
        assert translate(translator) == "1:one|fetcher", "repeated translation must not stack the transformer"

    def test_offline_copy_keeps_provided(self, translator):
        """An offline copy has no fetcher to query, so it must keep what the original derived."""
        translator.go_offline()
        copy = translator.copy()

        assert copy._tx._transformers.keys() == {"bitmasks"}
        assert translate(copy) == "1:one|fetcher"

    def test_restore_roundtrip(self, translator, tmp_path):
        path = tmp_path / "translator.pkl"
        translator.go_offline(path=path)

        restored: Translator[str, str, int] = Translator.restore(path)
        assert restored._tx._transformers.keys() == {"bitmasks"}
        assert translate(restored) == "1:one|fetcher"


class TestMultiFetcher:
    def test_serving_child_wins(self):
        """Only the child that serves a source (after conflict resolution) is asked for its transformer."""
        shared = {"shared": {"id": [1], "name": ["s1"]}}
        loser_data = {"shared": {"id": [1], "name": ["WRONG"]}, "only_b": {"id": [1], "name": ["b1"]}}

        winner = ProvidingFetcher(shared, {"shared": Marker("A")})
        loser = ProvidingFetcher(loser_data, {"shared": Marker("B"), "only_b": Marker("b")})
        multi = MultiFetcher[str, int](winner, loser, on_source_conflict="ignore")
        translator = Translator[str, str, int](multi).initialize_sources()

        assert translator.translate((1,), names="shared") == ("1:s1|A",)
        assert translator.translate((1,), names="only_b") == ("1:b1|b",)
        assert winner.queries == ["shared"]
        assert loser.queries == ["only_b"], "the outranked claim on 'shared' must not be queried"

    def test_unserved_source_returns_none(self):
        """The base contract returns None for any source; a KeyError would break substitutability."""
        multi = MultiFetcher[str, int](MemoryFetcher[str, int](DATA))
        assert multi.get_transformer("nope") is None

    def test_discarded_optional_child_is_not_queried(self):
        class FailingFetcher(ProvidingFetcher):
            def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:  # noqa: ARG002
                raise RuntimeError("discard me")

        healthy = ProvidingFetcher(DATA, {"bitmasks": Marker("ok")})
        failing = FailingFetcher({"gone": {"id": [1], "name": ["g1"]}}, {"gone": Marker("no")}, optional=True)
        multi = MultiFetcher[str, int](healthy, failing)
        translator = Translator[str, str, int](multi).initialize_sources()

        assert translator._tx._transformers.keys() == {"bitmasks"}
        assert failing.queries == []
        assert translate(translator) == "1:one|ok"


def test_interrupted_fetcher_pass_rolls_back():
    """A KeyboardInterrupt halfway through the fetcher pass must not leave half a set, which the retry would chain onto."""

    class NewEachTime(MemoryFetcher[str, int]):
        def get_transformer(self, source: str) -> Transformer[int]:
            return Marker(source)

    class InterruptOnSecond(Translator[str, str, int]):
        calls = 0

        def register_transformer(self, *args: Any, **kwargs: Any) -> None:
            super().register_transformer(*args, **kwargs)
            InterruptOnSecond.calls += 1
            if InterruptOnSecond.calls == 2:
                raise KeyboardInterrupt

    translator = InterruptOnSecond(NewEachTime(TWO_SOURCES), fmt="{name}")
    with pytest.raises(KeyboardInterrupt):
        translator.initialize_sources()
    assert translate(translator) == "one|bitmasks"
