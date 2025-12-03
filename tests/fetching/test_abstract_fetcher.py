import re
from copy import deepcopy
from pathlib import Path

import pytest

from id_translation.fetching import AbstractFetcher, CacheAccess, MemoryFetcher, exceptions
from id_translation.fetching.exceptions import CacheAccessNotAvailableError
from id_translation.fetching.types import FetchInstruction, IdsToFetch
from id_translation.mapping import Mapper
from id_translation.mapping.exceptions import MappingWarning
from id_translation.offline.types import PlaceholderTranslations


@pytest.fixture(scope="module")
def fetcher(data):
    return MemoryFetcher(data)


def test_unknown_sources(fetcher):
    with pytest.raises(exceptions.UnknownSourceError, match="edible_humans") as ec:
        fetcher.fetch([IdsToFetch("humans", {1, 2}), IdsToFetch("edible_humans", {1, 2})])
    assert {"edible_humans"} == ec.value.unknown_sources

    with pytest.raises(exceptions.UnknownSourceError, match="edible_humans") as ec:
        fetcher.map_placeholders("edible_humans", placeholders=["not-used"])
    assert {"edible_humans"} == ec.value.unknown_sources


def test_fetch_all_forbidden(data):
    fetcher: MemoryFetcher[str, int] = MemoryFetcher(data, allow_fetch_all=False)
    match = re.escape(f"Operation 'FETCH_ALL' not allowed by {fetcher}.")
    with pytest.raises(exceptions.ForbiddenOperationError, match=match):
        fetcher.fetch_all()


def test_unknown_placeholders(fetcher):
    with pytest.raises(exceptions.UnknownPlaceholderError, match=r"{'number_of_legs'} not recognized"):
        fetcher.fetch([IdsToFetch("humans", set())], ("id", "number_of_legs"), {"number_of_legs"})


@pytest.mark.parametrize(
    "selective_fetch_all, required, expected",
    [
        (True, ("id", "name"), {"animals", "humans"}),
        (False, (), {"animals", "humans", "big_table", "huge_table"}),
    ],
)
def test_selective_fetch_all(data, selective_fetch_all, required, expected):
    with pytest.warns(MappingWarning, match="on_unmapped='raise'"):
        fetcher: AbstractFetcher[str, int] = MemoryFetcher(
            data,
            selective_fetch_all=selective_fetch_all,
            mapper=Mapper("equality", on_unmapped="raise"),
        )
    assert set(fetcher.fetch_all(required=required)) == expected


def test_test_crashes_with_selective_fetch_all_disabled(data):
    with pytest.raises(exceptions.UnknownPlaceholderError):
        MemoryFetcher(data, selective_fetch_all=False).fetch_all(required=("id", "name"))


class TestCache:
    def test_from_cache(self, windows_hack_temp_dir):
        fetcher = CachingFetcher(windows_hack_temp_dir)
        self._run(fetcher)

    def test_no_access(self):
        with pytest.raises(CacheAccessNotAvailableError, match=r"documentation/examples/caching/caching.html"):
            _ = MemoryFetcher({}).cache_access

    def test_clone(self, windows_hack_temp_dir):
        original = CachingFetcher(windows_hack_temp_dir)

        copy = deepcopy(original)
        assert id(original) != id(copy)
        assert id(original.cache_access) != id(copy.cache_access)
        assert id(original.calls) != id(copy.calls)

        assert id(original.cache_access.parent) == id(original)
        assert id(copy.cache_access.parent) == id(copy)

        self._run(original)
        self._run(copy)

    @staticmethod
    def _run(fetcher: "CachingFetcher") -> None:
        ids_to_fetch = [IdsToFetch("people", {1999})]
        expected = {"people": PlaceholderTranslations("people", ("id", "name"), ((1999, "Sofia"),), 0)}

        calls = fetcher.calls

        assert calls == {"store": 0, "load": 0, "fetch": 0}

        # Initial store. We get one load-attempt (which returns None) followed by a store.
        assert fetcher.fetch_all() == expected
        assert calls == {"store": 1, "load": 1, "fetch": 1}

        # Subsequent calls are loaded from cache, but does not restore it.
        assert fetcher.fetch_all() == expected
        assert calls == {"store": 1, "load": 2, "fetch": 1}

        # Including (and especially) regular data requests
        assert fetcher.fetch(ids_to_fetch) == expected
        assert calls == {"store": 1, "load": 3, "fetch": 1}

        # Clear the cache.
        assert isinstance(fetcher.cache_access, StoreFetchAllCacheAccess)
        fetcher.cache_access.reset()

        assert fetcher.fetch(ids_to_fetch) == expected
        assert calls == {"store": 1, "load": 4, "fetch": 2}


class StoreFetchAllCacheAccess(CacheAccess[str, int]):
    def __init__(self, root: Path, calls: dict[str, int]) -> None:
        super().__init__()
        self._root = root
        self._calls = calls
        self._cache: PlaceholderTranslations[str] | None = None

    def reset(self) -> None:
        self._cache = None

    def store(self, instr: FetchInstruction[str, int], translations: PlaceholderTranslations[str]) -> None:
        assert instr.source == "people"
        if instr.ids is not None:
            return

        self._calls["store"] += 1
        self._cache = translations

    def load(self, instr: FetchInstruction[str, int]) -> PlaceholderTranslations[str] | None:
        assert instr.source == "people"
        self._calls["load"] += 1
        return self._cache


class CachingFetcher(MemoryFetcher[str, int]):
    def __init__(self, windows_hack_temp_dir):
        self.calls = {"store": 0, "load": 0, "fetch": 0}
        super().__init__(
            data={"people": {1999: "Sofia"}},
            cache_access=StoreFetchAllCacheAccess(windows_hack_temp_dir, self.calls),
        )

    @property
    def cache_enabled(self) -> bool:
        return True

    def fetch_translations(self, instr):
        self.calls["fetch"] += 1
        return super().fetch_translations(instr)


class TestBadImplementation:
    def test_initialize_sources(self):
        fetcher = BadFetcher()
        match = r"Call to .*test_abstract_fetcher\.BadFetcher.initialize_sources\(\) failed."
        with pytest.raises(RuntimeError, match=match):
            fetcher.initialize_sources()

    def test_fetch(self):
        fetcher = BadFetcher()
        match = r"Call to .*test_abstract_fetcher\.BadFetcher.initialize_sources\(\) failed."
        with pytest.raises(RuntimeError, match=match):
            fetcher.fetch([IdsToFetch("source", {1})])

    def test_id_column(self):
        fetcher = BadFetcher()
        with pytest.raises(TypeError, match=r"Bad candidates=\[\] argument; must be a non-empty collection."):
            fetcher.id_column("source", candidates=[])


class BadFetcher(AbstractFetcher[str, int]):
    def _initialize_sources(self, _):
        return None

    def fetch_translations(self, instr):
        raise NotImplementedError
