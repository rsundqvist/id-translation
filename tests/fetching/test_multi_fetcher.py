from collections.abc import Collection

import pandas as pd
import pytest
from id_translation import Translator
from id_translation.fetching import AbstractFetcher, MemoryFetcher, MultiFetcher, SqlFetcher, exceptions
from id_translation.fetching.exceptions import FetcherWarning
from id_translation.fetching.types import IdsToFetch
from id_translation.offline.types import PlaceholderTranslations, SourcePlaceholderTranslations

from ..conftest import ROOT


@pytest.fixture(scope="module")
def fetchers(data: dict[str, pd.DataFrame]) -> Collection[AbstractFetcher[str, int]]:
    humans_fetcher: MemoryFetcher[str, int] = MemoryFetcher({"humans": data["humans"]})
    empty_fetcher: MemoryFetcher[str, int] = MemoryFetcher(optional=True)
    everything_fetcher: MemoryFetcher[str, int] = MemoryFetcher(data)

    with pytest.warns(FetcherWarning, match="empty"):
        sql_fetcher: SqlFetcher[int] = SqlFetcher("sqlite://", whitelist_tables=())  # No tables allowed!
    return humans_fetcher, empty_fetcher, everything_fetcher, sql_fetcher


@pytest.fixture(scope="module")
def multi_fetcher(fetchers):
    fetcher = MultiFetcher(*fetchers, duplicate_source_discovered_action="ignore")
    yield fetcher
    fetcher.close()


@pytest.fixture(scope="module")
def expected(data):
    return MemoryFetcher(data).fetch_all()


def test_sources(multi_fetcher):
    assert sorted(multi_fetcher.sources) == ["animals", "big_table", "huge_table", "humans"]


def test_sources_per_child(multi_fetcher):
    children = multi_fetcher.children
    assert len(children) == 3
    assert children[0].sources == ["humans"]
    assert sorted(children[1].sources) == ["animals", "big_table", "huge_table", "humans"]
    assert sorted(children[2].sources) == []


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
    children: list[MemoryFetcher[str, int]] = [MemoryFetcher({f"{i=}": {"id": [1, 2, 3]}}) for i in range(10)]
    fetcher: MultiFetcher[str, int] = MultiFetcher(*children)

    ans: SourcePlaceholderTranslations[str] = {}
    source_ranks: dict[str, int] = {}

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


def test_fetch(multi_fetcher: MultiFetcher[str, int], data: dict[str, pd.DataFrame]) -> None:
    required = {"id"}
    placeholders = {"name", "is_nice"}

    sampled = [IdsToFetch(source, set(df.id)) for source, df in data.items()]
    memory_fetcher: MemoryFetcher[str, int] = MemoryFetcher(data)
    expected: SourcePlaceholderTranslations[str] = memory_fetcher.fetch(sampled, placeholders, required=required)
    actual = multi_fetcher.fetch(sampled, placeholders, required=required)

    assert actual == expected


def test_ranks(multi_fetcher, fetchers):
    humans_fetcher, empty_fetcher, everything_fetcher, sql_fetcher = fetchers

    assert len(multi_fetcher.children) == 3
    assert humans_fetcher in multi_fetcher.children
    assert empty_fetcher not in multi_fetcher.children
    assert everything_fetcher in multi_fetcher.children
    assert sql_fetcher in multi_fetcher.children

    assert multi_fetcher._id_to_rank[id(humans_fetcher)] == 0
    assert multi_fetcher._id_to_rank[id(everything_fetcher)] == 2
    assert multi_fetcher._id_to_rank[id(sql_fetcher)] == 3


def test_from_config():
    main_config = ROOT.joinpath("config.imdb.toml")
    extra_children = [
        ROOT.joinpath("config.toml"),
        ROOT.joinpath("config.toml"),
    ]
    Translator.from_config(main_config, extra_children)


class TestOptionalFetchers:
    def test_no_crashes_one_optional(self):
        self._run(
            children=[
                CrashFetcher(False, optional=False),
                CrashFetcher(False, optional=True),
            ],
            expected=[0],
        )

    def test_optional_crash(self):
        self._run(
            children=[
                CrashFetcher(False, optional=False),
                CrashFetcher(True, optional=True),
            ],
            expected=[0],
        )

    def test_non_optional_crash(self):
        self._run(
            children=[
                CrashFetcher(True, optional=False),
                CrashFetcher(True, optional=True),
            ],
            expected=None,
        )

    def test_all_optional_crash(self):
        with pytest.warns(UserWarning, match="No fetchers"):
            self._run(
                children=[
                    CrashFetcher(True, optional=True),
                    CrashFetcher(True, optional=True),
                ],
                expected=[],
            )

    def test_sql_fetcher_crash(self):
        self._run(
            children=[
                CrashFetcher(False, optional=False),
                SqlFetcher("postgresql+pg8000://bad_user:bad-password@localhost", optional=True),
            ],
            expected=[0],
        )

    @staticmethod
    def _run(children, expected):
        fetcher = MultiFetcher(*children, duplicate_source_discovered_action="ignore")

        if expected is None:
            with pytest.raises(ValueError, match="I crashed!"):
                fetcher.initialize_sources()
        else:
            fetcher.initialize_sources()
            actual = set(fetcher.children)
            assert len(actual) == len(expected)
            for c in (children[i] for i in expected):
                assert c in actual


class CrashFetcher(MemoryFetcher[str, int]):
    def __init__(self, crash: bool, *, optional: bool):
        super().__init__({"source": {"id": [1]}}, optional=optional)
        self.crash = crash

    def __str__(self) -> str:
        return f"CrashFetcher({self.crash}, optional={self.optional})"

    def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:
        if self.crash:
            raise ValueError("I crashed!")

        return super()._initialize_sources(task_id)


@pytest.mark.filterwarnings("ignore:No fetchers:UserWarning")
class TestNoSources:
    def test_required(self, caplog):
        fetcher: MultiFetcher[str, int] = MultiFetcher(MemoryFetcher({}, optional=False))
        fetcher.initialize_sources()

        assert len(fetcher.children) == 1

        assert len(caplog.records) == 2
        assert caplog.records[0].levelname == "WARNING"
        assert "does not provide any sources" in caplog.messages[0]
        assert "useless" in caplog.messages[1]

    @pytest.mark.parametrize("level", ["DEBUG", "WARNING"])
    def test_optional(self, caplog, level):
        fetcher: MultiFetcher[str, int] = MultiFetcher(
            MemoryFetcher({}, optional=True), optional_fetcher_discarded_log_level=level
        )
        fetcher.initialize_sources()

        assert len(fetcher.children) == 0

        assert len(caplog.records) == 1
        assert caplog.records[0].levelname == level
        assert caplog.messages[0].startswith("Discard")
