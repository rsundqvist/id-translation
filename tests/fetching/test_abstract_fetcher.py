from copy import deepcopy
from pathlib import Path

import pandas as pd
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
    fetcher: AbstractFetcher[str, int] = MemoryFetcher(data)
    fetcher._allow_fetch_all = False

    with pytest.raises(exceptions.ForbiddenOperationError, match=f"{AbstractFetcher._FETCH_ALL!r} not supported"):
        fetcher.fetch_all()


def test_unknown_placeholders(fetcher):
    with pytest.raises(exceptions.UnknownPlaceholderError, match="{'number_of_legs'} not recognized"):
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
        with pytest.raises(CacheAccessNotAvailableError, match="documentation/examples/caching/caching.html"):
            _ = MemoryFetcher().cache_access

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
        from id_translation.offline.types import PlaceholderTranslations

        ids_to_fetch = [IdsToFetch("people", {1999})]
        expected = {"people": PlaceholderTranslations("people", ("id", "name"), [[1999, "Sofia"]], 0)}

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

        # Clear the cache. The AbstractFetcher
        assert isinstance(fetcher.cache_access, StoreFetchAllCacheAccess)
        fetcher.cache_access.reset()

        assert fetcher.fetch(ids_to_fetch) == expected
        assert calls == {"store": 1, "load": 4, "fetch": 2}


class StoreFetchAllCacheAccess(CacheAccess[str, int]):
    def __init__(self, root: Path, calls: dict[str, int]) -> None:
        super().__init__()
        self._root = root
        self._calls = calls

    def reset(self) -> None:
        self._path("people").unlink()

    def _path(self, source: str) -> Path:
        assert source == "people"
        return self._root / f"{source}.ftr"

    def store(self, instr: FetchInstruction[str, int], translations: PlaceholderTranslations[str]) -> None:
        if instr.ids is not None:
            return

        self._calls["store"] += 1
        df = pd.DataFrame.from_dict(translations.to_dict())
        path = self._path(translations.source)
        df.to_feather(path)

    def load(self, instr: FetchInstruction[str, int]) -> PlaceholderTranslations[str] | None:
        self._calls["load"] += 1
        path = self._path(instr.source)

        if not path.is_file():
            return None

        df = pd.read_feather(path)
        return PlaceholderTranslations.from_dataframe(instr.source, df)


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
        with pytest.raises(RuntimeError, match=r"Call to BadFetcher._initialize_sources\(\) failed."):
            fetcher.initialize_sources()

    def test_fetch(self):
        fetcher = BadFetcher()
        with pytest.raises(RuntimeError, match=r"Call to BadFetcher._initialize_sources\(\) failed."):
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
