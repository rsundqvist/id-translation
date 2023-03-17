from typing import Dict

import pandas as pd
import pytest
from rics.collections.misc import as_list

from id_translation.fetching import AbstractFetcher, CacheAccess, MemoryFetcher, exceptions
from id_translation.fetching.types import IdsToFetch
from id_translation.mapping import Mapper


@pytest.fixture(scope="module")
def fetcher(data):
    return MemoryFetcher(data)


def test_unknown_sources(fetcher):
    with pytest.raises(exceptions.UnknownSourceError) as ec:
        fetcher.fetch([IdsToFetch("humans", [1, 2]), IdsToFetch("edible_humans", [1, 2])])
    assert str({"edible_humans"}) in str(ec.value)

    with pytest.raises(exceptions.UnknownSourceError) as ec:
        fetcher.get_placeholders("edible_humans")
    assert str({"edible_humans"}) in str(ec.value)


def test_fetch_all_forbidden(data):
    fetcher: AbstractFetcher[str, int] = MemoryFetcher(data)
    fetcher._allow_fetch_all = False

    with pytest.raises(exceptions.ForbiddenOperationError, match=f"{AbstractFetcher._FETCH_ALL!r} not supported"):
        fetcher.fetch_all()


def test_unknown_placeholders(fetcher):
    with pytest.raises(exceptions.UnknownPlaceholderError, match="{'number_of_legs'} not recognized"):
        fetcher.fetch([IdsToFetch("humans", [])], ("id", "number_of_legs"), {"number_of_legs"})


@pytest.mark.parametrize(
    "selective_fetch_all, required, expected",
    [
        (True, ("id", "name"), {"animals", "humans"}),
        (False, (), {"animals", "humans", "big_table", "huge_table"}),
    ],
)
def test_selective_fetch_all(data, selective_fetch_all, required, expected):
    fetcher: AbstractFetcher[str, int] = MemoryFetcher(
        data,
        selective_fetch_all=selective_fetch_all,
        mapper=Mapper(unmapped_values_action="raise"),
    )
    assert set(fetcher.fetch_all(required=required)) == expected


def test_test_crashes_with_selective_fetch_all_disabled(data):
    with pytest.raises(exceptions.UnknownPlaceholderError):
        MemoryFetcher(data, selective_fetch_all=False).fetch_all(required=("id", "name"))


@pytest.fixture(scope="module")
def fetch_all_cache_dir(windows_hack_temp_dir):
    yield windows_hack_temp_dir.joinpath("abstract-fetcher-cache")


@pytest.mark.parametrize(
    "operations, expected_call_counts, clear",
    [
        # Order matters!
        (["all", "one", "all"], [4, 4, 4], False),
        (["one", "all", "all"], [0, 0, 0], False),
        (["one", "all", "all"], [1, 5, 5], True),
        (["one", "one", "one", "one", "all", "one"], [1, 2, 3, 4, 8, 8], True),
        (["one", "one", "one", "one", "all", "one"], [0, 0, 0, 0, 0, 0], False),
    ],
    ids=lambda v: "_".join(map(str, as_list(v))),
)
def test_cache_with_call_count(
    fetch_all_cache_dir,
    fetcher,
    operations,
    expected_call_counts,
    clear,
):
    CacheAccess.base_cache_dir_for_all_fetchers = lambda _: fetch_all_cache_dir.joinpath("test_cache_with_call_count")  # type: ignore

    assert len(operations) == len(expected_call_counts)
    expected_data = fetcher.fetch_all()

    test_fetcher = CacheTestFetcher(fetcher._data, key="test_cache_with_call_count")
    if clear:
        test_fetcher.clear_cache("test case")

    for i, (op, expected_count) in enumerate(zip(operations, expected_call_counts)):
        msg = f"Step {i}: {op}({expected_count})"

        if op == "all":
            fetch_all_actual = test_fetcher.fetch_all()
            assert fetch_all_actual == expected_data, msg
        else:
            fetch_actual = test_fetcher.fetch([IdsToFetch("humans", [1, 2])])["humans"]
            expected = expected_data["humans"]
            assert fetch_actual == expected, msg

        assert test_fetcher.fetch_translations_call_count == expected_count, msg


def test_cache_doesnt_refresh_itself(data, fetch_all_cache_dir):
    CacheAccess.base_cache_dir_for_all_fetchers = lambda _: fetch_all_cache_dir.joinpath("doesnt_refresh_itself")  # type: ignore
    test_fetcher = CacheTestFetcher(data, key="doesnt_refresh_itself")
    test_fetcher.fetch_all()
    metadata_path = test_fetcher._create_cache_access().metadata_path
    expected_metadata = metadata_path.read_text()

    for _ in range(4):
        test_fetcher.fetch_all()

    actual_metadata = metadata_path.read_text()
    assert actual_metadata == expected_metadata


def test_corrupted_cache(caplog, fetcher, fetch_all_cache_dir):
    test_root = fetch_all_cache_dir.joinpath("test_corrupted_cache")
    CacheAccess.base_cache_dir_for_all_fetchers = lambda *_: test_root  # type: ignore
    test_fetcher = CacheTestFetcher(fetcher._data, key="test_corrupted_cache")
    test_fetcher.fetch_all()
    caplog.clear()

    access = test_fetcher._create_cache_access()
    access.data_path.write_text("Corrupted data!")
    with caplog.at_level("DEBUG"):
        assert test_fetcher._get_cached_translations("humans") is None

    assert not access.data_path.exists()
    assert not access.metadata_path.exists()

    wanted_substrings = [access.data_path, access.metadata_path]
    expected = list(map(str, wanted_substrings))
    actual = []
    for message in caplog.messages:
        for w in expected:
            if w in message:
                actual.append(w)

    assert actual == expected, "Some wanted log messages weren't found."
    assert test_root.exists()
    CacheAccess.clear_all_cache_data()
    assert not test_root.exists()


def test_placeholders_invalidate_cache(data, fetch_all_cache_dir):
    CacheAccess.base_cache_dir_for_all_fetchers = lambda _: fetch_all_cache_dir.joinpath("placeholders")  # type: ignore
    data = data.copy()

    original_metadata = CacheTestFetcher(data, key="new_placeholders")._create_cache_access()._metadata

    del data["animals"]
    no_animals_metadata = CacheTestFetcher(data, key="new_placeholders")._create_cache_access()._metadata
    assert "Expected sources=['" in no_animals_metadata.is_equivalent(original_metadata)

    del data["humans"]["name"]
    no_name_humans = CacheTestFetcher(data, key="new_placeholders")._create_cache_access()._metadata
    assert "For source='humans', expected placeholders" in no_animals_metadata.is_equivalent(no_name_humans)


def test_new_cache_key_invalidates_cache():
    first_metadata = CacheTestFetcher({}, key="first")._create_cache_access()._metadata
    second_metadata = CacheTestFetcher({}, key="second")._create_cache_access()._metadata
    assert str(second_metadata.cache_keys) in second_metadata.is_equivalent(first_metadata)


class CacheTestFetcher(MemoryFetcher[str, int]):
    def __init__(self, data: Dict[str, pd.DataFrame], key: str) -> None:
        super().__init__(data, fetch_all_cache_max_age="100d", cache_keys=[CacheTestFetcher.__name__] + [key])
        self.fetch_translations_call_count = 0
        self._online = True

    def set_online(self, online: bool) -> None:
        self._online = online

    @property
    def online(self) -> bool:
        return self._online

    def fetch_translations(self, instr):
        self.fetch_translations_call_count += 1
        return super().fetch_translations(instr)
