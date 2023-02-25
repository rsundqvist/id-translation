import pytest

from id_translation.fetching import AbstractFetcher, MemoryFetcher, exceptions
from id_translation.fetching.types import IdsToFetch


@pytest.fixture(scope="module")
def fetcher(data):
    return MemoryFetcher(data)


def test_unknown_sources(fetcher):
    with pytest.raises(exceptions.UnknownSourceError) as ec:
        fetcher.fetch([IdsToFetch("humans", None), IdsToFetch("edible_humans", [1, 2])])
    assert str({"edible_humans"}) in str(ec.value)

    with pytest.raises(exceptions.UnknownSourceError) as ec:
        fetcher.get_placeholders("edible_humans")
    assert str({"edible_humans"}) in str(ec.value)


def test_fetch_all_forbidden(data):
    fetcher: AbstractFetcher[str, int] = MemoryFetcher(data)
    fetcher._allow_fetch_all = False

    with pytest.raises(exceptions.ForbiddenOperationError) as ec:
        fetcher.fetch([IdsToFetch("humans", None), IdsToFetch("animals", [1, 2])])
    assert f"{repr(AbstractFetcher._FETCH_ALL)} not supported" in str(ec.value)

    with pytest.raises(exceptions.ForbiddenOperationError) as ec:
        fetcher.fetch_all()
    assert f"{repr(AbstractFetcher._FETCH_ALL)} not supported" in str(ec.value)


def test_unknown_placeholders(fetcher):
    with pytest.raises(exceptions.UnknownPlaceholderError) as ec:
        fetcher.fetch([IdsToFetch("humans", None)], ("id", "number_of_legs"), {"number_of_legs"})
    assert "{'number_of_legs'} not recognized" in str(ec.value)
