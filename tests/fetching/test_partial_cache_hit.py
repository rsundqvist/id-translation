"""Partial cache hits: the fetcher fetches only the uncovered IDs and merges them with the cached rows."""

import dataclasses

import pytest

from id_translation import Translator
from id_translation.fetching import AbstractFetcher, CacheAccess
from id_translation.fetching.exceptions import ImplementationError, UnknownIdPlaceholderError
from id_translation.fetching.types import PartialCacheHit
from id_translation.mapping import Mapper
from id_translation.offline.types import PlaceholderTranslations
from id_translation.types import ID

PEOPLE = {
    1: {"name": "Alice", "email": "a@x"},
    2: {"name": "Bob", "email": "b@x"},
    3: {"name": "Cara", "email": "c@x"},
}


class RecordingFetcher(AbstractFetcher[str, int]):
    """Returns exactly the requested IDs/placeholders and records every source call."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calls: list[tuple[tuple[str, ...], set[int] | None]] = []

    def _initialize_sources(self, task_id):  # noqa: ARG002
        return {"people": [ID, "name", "email"]}

    def fetch_translations(self, instr):
        self.calls.append((tuple(instr.placeholders), None if instr.ids is None else set(instr.ids)))
        ids = instr.ids if instr.ids is not None else PEOPLE
        records = [tuple(i if c == ID else PEOPLE[i][c] for c in instr.placeholders) for i in ids if i in PEOPLE]
        return PlaceholderTranslations("people", tuple(instr.placeholders), records)


class StubCache(CacheAccess[str, int]):
    """Returns a fixed ``load`` result and records ``store`` calls."""

    def __init__(self, result: object) -> None:
        super().__init__()
        self.result = result
        self.stored: list[set[int] | None] = []

    def load(self, instr):  # noqa: ARG002
        return self.result

    def store(self, instr, translations):  # noqa: ARG002
        self.stored.append(instr.ids)


def make(result: object, *, fmt: str = "{id}:{name}") -> tuple[Translator[str, str, int], RecordingFetcher, StubCache]:
    cache = StubCache(result)
    fetcher = RecordingFetcher(cache_access=cache, allow_fetch_all=True)
    return Translator(fetcher, fmt=fmt), fetcher, cache


def cached(placeholders: tuple[str, ...], *ids: int) -> PlaceholderTranslations[str]:
    records = [tuple(i if col == ID else PEOPLE[i][col] for col in placeholders) for i in ids]
    return PlaceholderTranslations("people", placeholders, records)


def partial(placeholders: tuple[str, ...], *ids: int, covered: set[int] | None = None) -> PartialCacheHit[str, int]:
    return PartialCacheHit(cached(placeholders, *ids), covered=covered)


def test_partial_fetches_only_the_complement():
    translator, fetcher, cache = make(partial((ID, "name"), 1, covered={1}))

    assert translator.translate([1, 2, 3], names="people") == ["1:Alice", "2:Bob", "3:Cara"]
    assert fetcher.calls == [((ID, "name"), {2, 3})]  # only the missing IDs were fetched
    assert cache.stored == [{2, 3}]  # store() received only the complement


def test_covered_defaults_to_returned_rows():
    # No explicit `covered` -> the fetcher derives it from the rows in `translations`.
    translator, fetcher, _ = make(partial((ID, "name"), 1, 2))

    assert translator.translate([1, 2, 3], names="people") == ["1:Alice", "2:Bob", "3:Cara"]
    assert fetcher.calls == [((ID, "name"), {3})]


def test_no_missing_does_not_fetch():
    translator, fetcher, cache = make(partial((ID, "name"), 1, 2))

    assert translator.translate([1, 2], names="people") == ["1:Alice", "2:Bob"]
    assert fetcher.calls == []  # fully covered
    assert cache.stored == []


def test_negative_caching_suppresses_refetch():
    # 99 is vouched for via `covered` but has no row (known-missing) -> never refetched.
    translator, fetcher, _ = make(partial((ID, "name"), 1, covered={1, 99}))

    out = translator.translate([1, 99], names="people")
    assert out[0] == "1:Alice"
    assert fetcher.calls == []  # nothing fetched despite 99 being absent


def test_empty_hit_steers_refetch_layout_for_cohesion():
    # Cache holds a wide layout; an empty hit carrying that layout makes the fetcher widen the refetch.
    translator, fetcher, cache = make(partial((ID, "name", "email"), covered=set()), fmt="{id}:{name}")

    assert translator.translate([1, 2], names="people") == ["1:Alice", "2:Bob"]
    assert fetcher.calls == [((ID, "name", "email"), {1, 2})]  # widened to the cache's layout
    assert cache.stored == [{1, 2}]


def test_partial_merges_at_wide_layout():
    translator, fetcher, _ = make(partial((ID, "name", "email"), 1, covered={1}), fmt="{id}:{name}")

    assert translator.translate([1, 2], names="people") == ["1:Alice", "2:Bob"]
    assert fetcher.calls == [((ID, "name", "email"), {2})]  # complement fetched at the wide layout -> clean merge


def test_partial_cache_hit_rejected_for_fetch_all():
    translator, _, _ = make(partial((ID, "name"), covered=set()))

    with pytest.raises(ImplementationError, match="fetch-all"):
        translator.go_offline()


def test_partial_hit_layout_mismatch_is_an_implementation_error():
    class NarrowFetcher(RecordingFetcher):
        def fetch_translations(self, instr):
            pht = super().fetch_translations(instr)
            return PlaceholderTranslations(pht.source, pht.placeholders[:2], [r[:2] for r in pht.records])

    cache = StubCache(partial((ID, "name", "email"), 1, covered={1}))
    translator: Translator[str, str, int] = Translator(NarrowFetcher(cache_access=cache), fmt="{id}:{name}")

    with pytest.raises(ImplementationError, match="does not match fetched layout"):
        translator.translate([1, 2], names="people")
    assert cache.stored == [], "a rejected complement must not be cached"


def test_partial_hit_with_numpy_array_records():
    # `records` may be a numpy array; the merge must not trip the ambiguous-truth-value error (`not arr`).
    np = pytest.importorskip("numpy")

    class NumpyFetcher(RecordingFetcher):
        def fetch_translations(self, instr):
            pht = super().fetch_translations(instr)
            return dataclasses.replace(pht, records=np.asarray(pht.records, dtype=object))

    cached_pht = PlaceholderTranslations("people", (ID, "name"), np.array([[1, "Alice"]], dtype=object))
    cache = StubCache(PartialCacheHit(cached_pht, covered={1}))
    fetcher = NumpyFetcher(cache_access=cache, allow_fetch_all=True)
    translator: Translator[str, str, int] = Translator(fetcher, fmt="{id}:{name}")

    assert translator.translate([1, 2, 3], names="people") == ["1:Alice", "2:Bob", "3:Cara"]
    assert fetcher.calls == [((ID, "name"), {2, 3})]


def test_partial_hit_rows_without_id_placeholder():
    cached_pht = PlaceholderTranslations("people", ("name",), [("Alice",)])
    translator, _, _ = make(PartialCacheHit(cached_pht))

    with pytest.raises(UnknownIdPlaceholderError, match="no 'id' placeholder"):
        translator.translate([1, 2], names="people")


def test_fetched_rows_win_over_stale_cached_rows():
    # Fetchers may over-return (e.g. SqlFetcher range queries); fresh rows must shadow stale cached ones.
    class RangeFetcher(RecordingFetcher):
        def fetch_translations(self, instr):
            self.calls.append((tuple(instr.placeholders), None if instr.ids is None else set(instr.ids)))
            records = [tuple(i if c == ID else PEOPLE[i][c] for c in instr.placeholders) for i in sorted(PEOPLE)]
            return PlaceholderTranslations("people", tuple(instr.placeholders), records)

    stale = PlaceholderTranslations("people", (ID, "name"), [(1, "STALE")])
    cache = StubCache(PartialCacheHit(stale))
    fetcher = RangeFetcher(cache_access=cache, allow_fetch_all=True)
    translator: Translator[str, str, int] = Translator(fetcher, fmt="{id}:{name}")

    assert translator.translate([1, 2], names="people") == ["1:Alice", "2:Bob"]
    assert fetcher.calls == [((ID, "name"), {2})]


def test_loaded_translations_are_not_mutated():
    # A cache may return the same object every time; mapping placeholder names back must not rename it in place.
    class CodeFetcher(RecordingFetcher):
        def _initialize_sources(self, task_id):  # noqa: ARG002
            return {"people": ["code", "name"]}

    shared = PlaceholderTranslations("people", (ID, "name"), [(1, "Alice")])
    fetcher = CodeFetcher(cache_access=StubCache(shared), mapper=Mapper(overrides={ID: "code"}))

    translator: Translator[str, str, int] = Translator(fetcher)
    assert translator.translate([1], names="people") == ["1:Alice"]
    assert shared.placeholders == (ID, "name")
    assert shared.placeholder_aliases == {}
