import pytest

from id_translation.fetching import Fetcher, MultiFetcher
from id_translation.fetching.types import IdsToFetch
from id_translation.testing import TestFetcher as _TestFetcher  # Aliased: pytest collects Test* classes


@pytest.mark.parametrize("multi", [False, True])
def test_fetch_returns_required(multi):
    fetcher: Fetcher[str, int] = _TestFetcher(["people"])
    if multi:
        fetcher = MultiFetcher(fetcher)

    actual = fetcher.fetch([IdsToFetch("people", {1})], ("name",), required=iter(["title"]))["people"]

    assert set(actual.placeholders) == {"id", "name", "title"}
