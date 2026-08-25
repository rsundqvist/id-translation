"""Tests for fetcher-provided transformers; see ``Fetcher.get_transformer``."""

import pickle
import threading
import warnings
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from id_translation import Translator
from id_translation.fetching import MemoryFetcher, MultiFetcher
from id_translation.offline.types import PlaceholderTranslations
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
    """The base implementation provides nothing, for any source."""
    fetcher = MemoryFetcher[str, int](DATA)
    assert fetcher.get_transformer("bitmasks") is None

    translator = Translator[str, str, int](fetcher).initialize_sources()
    assert translator.transformers == {}


def test_provided_transformer_is_applied():
    """The headline use case: the fetcher ships the wiring; the user writes no registration code."""
    fetcher = ProvidingFetcher(TWO_SOURCES, {"bitmasks": Marker("fetcher")})
    translator = Translator[str, str, int](fetcher)

    assert translate(translator) == "1:one|fetcher"
    assert translator.transformers.keys() == {"bitmasks"}, "sources without a provided transformer must be untouched"
    assert translator.translate((1,), names="plain") == ("1:just-one",)


def test_chain_becomes_a_stack():
    first, second = Marker("first"), Marker("second")
    fetcher = ProvidingFetcher(DATA, {"bitmasks": [first, second]})
    translator = Translator[str, str, int](fetcher).initialize_sources()

    stack = translator.transformers["bitmasks"]
    assert isinstance(stack, TransformerStack)
    assert stack.transformers == (first, second), "members must keep the given order"
    assert translate(translator) == "1:one|first|second"


def test_offline_translator_is_not_queried():
    """Offline instances have no fetcher to query."""
    translator = Translator[str, str, int]({"bitmasks": {1: "one"}}).initialize_sources()
    assert translator.transformers == {}


def test_snapshot_without_query_state():
    """Snapshots written before `Fetcher.get_transformer` existed must still load, and copy."""
    translator = Translator[str, str, int]({"bitmasks": {1: "one"}})
    del translator._transformers_queried  # The state an older `Translator.restore` snapshot unpickles into.

    restored = pickle.loads(pickle.dumps(translator))  # noqa: S301
    assert restored.copy().translate((1,), names="bitmasks") == ("1:one",)


def test_live_dict_mutation_is_seen_by_the_query_pass():
    """The deprecated live dict bypasses `register_transformer`, but the query pass must still see what it wrote."""
    translator = Translator[str, str, int](ProvidingFetcher(DATA, {"bitmasks": Marker("fetcher")}))
    translator.transformers["bitmasks"] = Marker("sneaky")
    translator.initialize_sources()

    assert translate(translator) == "1:one|fetcher|sneaky", "chained onto, not replaced"


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

    def test_force_does_not_requery(self, translator, fetcher):
        translator.initialize_sources()
        translator.initialize_sources(force=True)

        assert Counter(fetcher.queries) == {"bitmasks": 1, "plain": 1}

    def test_late_source_is_not_queried(self, translator, fetcher):
        """Documents the gap: the query pass runs once, so late sources never receive their transformers."""
        fetcher.provide["late"] = Marker("late")
        translator.initialize_sources()

        fetcher._data["late"] = PlaceholderTranslations.make("late", {1: "late-one"})
        translator.initialize_sources(force=True)

        assert "late" in translator.sources, "precondition: forced re-discovery must pick up the new source"
        assert "late" not in fetcher.queries
        assert "late" not in translator.transformers


class TestOverlap:
    """A fetcher describes the source it serves, so its transformer chains ahead of anything declared for it."""

    def test_declared_and_provided_chain_fetcher_first(self):
        fetcher = ProvidingFetcher(TWO_SOURCES, {"bitmasks": Marker("fetcher")})
        translator = Translator[str, str, int](fetcher, transformers={"bitmasks": Marker("declared")})

        assert translate(translator) == "1:one|fetcher|declared", "the fetcher's runs first, as aux files do"

    def test_partially_overlapping_chain_adds_only_the_new_members(self):
        """`get_transformer` may answer with a sequence; only the part that is not already registered is new."""
        shared = Marker("shared")
        fetcher = ProvidingFetcher(TWO_SOURCES, {"bitmasks": [shared, Marker("extra")]})
        translator = Translator[str, str, int](fetcher, transformers={"bitmasks": shared})

        assert translate(translator) == "1:one|extra|shared", "'shared' is not chained onto itself"

    def test_provided_is_not_applied_twice(self):
        """Declaring exactly what the fetcher provides must not stack it onto itself."""
        provided = Marker("fetcher")
        fetcher = ProvidingFetcher(TWO_SOURCES, {"bitmasks": provided})
        translator = Translator[str, str, int](fetcher, transformers={"bitmasks": provided})

        assert translate(translator) == "1:one|fetcher", "applied exactly once"

    @pytest.fixture
    def fetcher(self) -> ProvidingFetcher:
        return ProvidingFetcher(TWO_SOURCES, {"bitmasks": Marker("fetcher")})

    def test_query_then_explicit_raises(self, fetcher):
        translator = Translator[str, str, int](fetcher).initialize_sources()

        with pytest.raises(ValueError, match="already registered"):
            translator.register_transformer("bitmasks", Marker("explicit"))

    def test_append_chains_onto_provided(self, fetcher):
        translator = Translator[str, str, int](fetcher).initialize_sources()
        translator.register_transformer("bitmasks", Marker("explicit"), on_existing="append")

        assert translate(translator) == "1:one|fetcher|explicit", "the provided transformer runs first"

    def test_overwrite_replaces_provided(self, fetcher):
        translator = Translator[str, str, int](fetcher).initialize_sources()
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
        """Not just TypeError/ValueError: a duplicate chain warns, and `-W error` makes that a UserWarning."""
        duplicate = Marker("duplicate")
        fetcher = ProvidingFetcher(TWO_SOURCES, {"bitmasks": Marker("fetcher"), "plain": [duplicate, duplicate]})
        translator = Translator[str, str, int](fetcher)

        with warnings.catch_warnings(), pytest.raises(UserWarning, match="Duplicate transformer"):
            warnings.simplefilter("error", UserWarning)
            translator.initialize_sources()

        assert translator.transformers == {}, "'bitmasks' must not survive the failed pass"


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
        """The same call must not query or not depending on whether the caller happened to translate first."""
        fetcher = ProvidingFetcher(TWO_SOURCES, {"bitmasks": Marker("fetcher"), "plain": Marker("fetcher")})
        translator = Translator[str, str, int](fetcher)
        if queried_first:
            translate(translator)

        explicit = Marker("explicit")
        copy = translator.copy(transformers={"bitmasks": explicit})

        assert copy.transformers == {"bitmasks": explicit}, "the override is the complete set"
        assert translate(copy) == "1:one|explicit"
        assert copy.translate((1,), names="plain") == ("1:just-one",), "not re-derived for unnamed sources either"

    def test_copy_before_query_queries_later(self, translator, fetcher):
        copy = translator.copy()

        assert translate(copy) == "1:one|fetcher"
        assert fetcher.queries == [], "the original must not be affected by the copy"
        assert translate(translator) == "1:one|fetcher"

    def test_copy_with_a_new_fetcher_queries_it(self):
        """A replacement fetcher has never been asked; its transformers must not be silently dropped."""
        translator = Translator[str, str, int](ProvidingFetcher(TWO_SOURCES, {"bitmasks": Marker("A")}))
        translate(translator)

        replacement = ProvidingFetcher(TWO_SOURCES, {"plain": Marker("B")})
        with pytest.warns(FutureWarning, match="replaces the data source"):
            copy = translator.copy(fetcher=replacement)

        assert translate(copy) == "1:one|A", "derived results are carried over"
        assert copy.translate((1,), names="plain") == ("1:just-one|B",), "the replacement fetcher's own must apply"
        assert "plain" in replacement.queries

    def test_copy_with_a_new_fetcher_chains_its_answer(self):
        """The replacement describes its own data, so its transformer runs ahead of the carried-over one."""
        translator = Translator[str, str, int](ProvidingFetcher(TWO_SOURCES, {"bitmasks": Marker("A")}))
        translate(translator)

        with pytest.warns(FutureWarning, match="replaces the data source"):
            copy = translator.copy(fetcher=ProvidingFetcher(TWO_SOURCES, {"bitmasks": Marker("B")}))
        assert translate(copy) == "1:one|B|A", "the new fetcher's answer runs first"

    def test_copy_with_none_transformers_starts_over(self, translator):
        """`None` means "derive on first use", exactly as it does in the constructor."""
        translate(translator)

        copy = translator.copy(transformers=None)
        assert copy.transformers == {}
        assert translate(copy) == "1:one|fetcher", "re-derived from the (copied) fetcher"

    def test_go_offline(self, translator):
        translator.go_offline()
        assert translate(translator) == "1:one|fetcher"
        assert translate(translator) == "1:one|fetcher", "repeated translation must not stack the transformer"

    def test_offline_copy_keeps_provided(self, translator):
        """An offline copy has no fetcher to query, so it must keep what the original derived."""
        translator.go_offline()
        copy = translator.copy()

        assert copy.transformers.keys() == {"bitmasks"}
        assert translate(copy) == "1:one|fetcher"

    def test_restore_roundtrip(self, translator, tmp_path):
        path = tmp_path / "translator.pkl"
        translator.go_offline(path=path)

        restored: Translator[str, str, int] = Translator.restore(path)
        assert restored.transformers.keys() == {"bitmasks"}
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

        assert translator.transformers.keys() == {"bitmasks"}
        assert failing.queries == []
        assert translate(translator) == "1:one|ok"
