import pytest
from rics.mapping import Mapper

from id_translation.fetching import AbstractFetcher, MemoryFetcher, exceptions
from id_translation.fetching.types import IdsToFetch


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
