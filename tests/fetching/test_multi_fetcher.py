from typing import Collection, Dict, List

import pandas as pd
import pytest

from id_translation import Translator
from id_translation.fetching import AbstractFetcher, MemoryFetcher, MultiFetcher, SqlFetcher, exceptions
from id_translation.fetching.types import IdsToFetch
from id_translation.offline.types import PlaceholderTranslations, SourcePlaceholderTranslations

from ..conftest import ROOT


@pytest.fixture(scope="module")
def fetchers(data: Dict[str, pd.DataFrame]) -> Collection[AbstractFetcher[str, int]]:
    humans_fetcher: MemoryFetcher[str, int] = MemoryFetcher({"humans": data["humans"]})
    empty_fetcher: MemoryFetcher[str, int] = MemoryFetcher()
    everything_fetcher: MemoryFetcher[str, int] = MemoryFetcher(data)
    sql_fetcher: SqlFetcher[int] = SqlFetcher("sqlite://", whitelist_tables=())  # No tables allowed!
    return humans_fetcher, empty_fetcher, everything_fetcher, sql_fetcher


@pytest.fixture(scope="module")
def multi_fetcher(fetchers):
    return MultiFetcher(*fetchers)


@pytest.fixture(scope="module")
def expected(data):
    return MemoryFetcher(data).fetch_all()


def test_sources(multi_fetcher):
    assert sorted(multi_fetcher.sources) == ["animals", "big_table", "huge_table", "humans"]


def test_sources_per_child(multi_fetcher):
    children = multi_fetcher.fetchers
    assert len(children) == 2
    assert children[0].sources == ["humans"]
    assert sorted(children[1].sources) == ["animals", "big_table", "huge_table", "humans"]


def test_placeholders(multi_fetcher):
    assert multi_fetcher.placeholders == {
        "animals": ["id", "name", "is_nice"],
        "humans": ["id", "name", "gender"],
        "big_table": ["id"],
        "huge_table": ["id"],
    }


def test_process_future():
    # Dict[str, Dict[str, List[int]]]
    # Dict[str, Dict[str, Sequence[Any]]]
    fetchers: List[MemoryFetcher[str, int]] = [MemoryFetcher({f"{i=}": {"id": [1, 2, 3]}}) for i in range(10)]
    fetcher: MultiFetcher[str, int] = MultiFetcher(*fetchers)

    ans: SourcePlaceholderTranslations[str] = {}
    source_ranks: Dict[str, int] = {}

    def make_and_process(rank):
        pht = PlaceholderTranslations.make("source", pd.DataFrame([rank], columns=["rank"]))
        fetcher._process_future_result({"source": pht}, rank=rank, source_ranks=source_ranks, ans=ans)
        return pht

    translations4 = make_and_process(4)
    assert ans["source"] == translations4

    with pytest.warns(exceptions.DuplicateSourceWarning):
        make_and_process(5)
    assert ans["source"] == translations4

    with pytest.warns(exceptions.DuplicateSourceWarning):
        translations2 = make_and_process(2)
    assert ans["source"] == translations2

    with pytest.warns(exceptions.DuplicateSourceWarning):
        translations0 = make_and_process(0)
    assert ans["source"] == translations0


def test_fetch_all(multi_fetcher, expected):
    with pytest.warns(exceptions.DuplicateSourceWarning):
        actual = multi_fetcher.fetch_all()
    assert actual == expected


def test_fetch(multi_fetcher: MultiFetcher[str, int], data: Dict[str, pd.DataFrame]) -> None:
    required = {"id"}
    placeholders = {"name", "is_nice"}

    sampled = [IdsToFetch(source, list(df.id)) for source, df in data.items()]
    memory_fetcher: MemoryFetcher[str, int] = MemoryFetcher(data)
    expected: SourcePlaceholderTranslations[str] = memory_fetcher.fetch(sampled, placeholders, required=required)
    actual = multi_fetcher.fetch(sampled, placeholders, required=required)

    assert actual == expected


def test_ranks(multi_fetcher, fetchers):
    humans_fetcher, empty_fetcher, everything_fetcher, sql_fetcher = fetchers

    assert len(multi_fetcher.fetchers) == 2
    assert humans_fetcher in multi_fetcher.fetchers
    assert everything_fetcher in multi_fetcher.fetchers

    assert multi_fetcher._id_to_rank[id(humans_fetcher)] == 0
    assert multi_fetcher._id_to_rank[id(everything_fetcher)] == 2


def test_from_config():
    main_config = ROOT.joinpath("config.imdb.toml")
    extra_fetchers = [
        ROOT.joinpath("config.toml"),
        ROOT.joinpath("config.imdb.toml"),
    ]
    Translator.from_config(main_config, extra_fetchers)
