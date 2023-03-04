import pytest

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
