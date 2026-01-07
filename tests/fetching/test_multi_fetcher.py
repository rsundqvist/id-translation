import logging
from collections.abc import Collection
from copy import deepcopy
from itertools import combinations

import pandas as pd
import pytest

from id_translation import Translator
from id_translation.fetching import AbstractFetcher, MemoryFetcher, MultiFetcher, SqlFetcher, exceptions
from id_translation.fetching.exceptions import FetcherWarning
from id_translation.fetching.types import IdsToFetch
from id_translation.offline.types import PlaceholderTranslations, SourcePlaceholderTranslations
from id_translation.types import IdTypes

from ..conftest import ROOT, NotCloneableFetcher

ALL_SOURCES = ["animals", "big_table", "huge_table", "humans"]


@pytest.fixture
def fetchers(data: dict[str, pd.DataFrame]) -> Collection[AbstractFetcher[str, int]]:
    primary_fetcher: MemoryFetcher[str, int] = MemoryFetcher({"humans": data["humans"], "animals": data["animals"]})
    empty_fetcher: MemoryFetcher[str, int] = MemoryFetcher({}, optional=True)

    data = {k: v for k, v in data.items() if k != "animals"}
    fallback_fetcher: MemoryFetcher[str, int] = MemoryFetcher(data)

    with pytest.warns(FetcherWarning, match="empty"):
        sql_fetcher: SqlFetcher[int] = SqlFetcher("sqlite://", whitelist_tables=())  # No tables allowed!
    return primary_fetcher, empty_fetcher, fallback_fetcher, sql_fetcher


@pytest.fixture
def multi_fetcher(fetchers):
    fetcher = MultiFetcher(*fetchers, on_source_conflict="ignore")
    yield fetcher
    fetcher.close()


@pytest.fixture(scope="module")
def expected(data):
    return MemoryFetcher(data).fetch_all()


def test_sources(multi_fetcher):
    assert sorted(multi_fetcher.sources) == ALL_SOURCES


def test_sources_per_child(multi_fetcher):
    children = multi_fetcher.children
    assert len(children) == 3
    assert children[0].sources == ["humans", "animals"]
    assert sorted(children[1].sources) == ["big_table", "huge_table", "humans"]
    assert sorted(children[2].sources) == []


def test_source_to_child_mapping(multi_fetcher):
    children = multi_fetcher.children
    assert len(children) == 3

    assert multi_fetcher.get_child("humans") == children[0]
    assert multi_fetcher.get_child("animals") == children[0]
    assert children[1].sources == ["humans", "big_table", "huge_table"]
    assert multi_fetcher.get_sources(children[1]) == ["big_table", "huge_table"]


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
        fetcher._process_future_result({"source": pht}, rank, source_ranks, ans, "FETCH", task_id=0)
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


def test_fetch_all(multi_fetcher, expected, caplog):
    actual = multi_fetcher.fetch_all()

    assert actual == expected

    dropped = (
        "Dropping translations for source='humans' returned by the rank-2 fetcher "
        "MemoryFetcher(sources=['humans', 'big_table', 'huge_table']"
    )

    for record in caplog.records:
        if record.getMessage().startswith(dropped):
            assert record.levelno == logging.DEBUG, "should be DEBUG during fetch_all"
            return

    raise AssertionError(f"not found: {dropped!r}")


@pytest.mark.parametrize(
    "sources",
    [
        *combinations(ALL_SOURCES, 1),
        *combinations(ALL_SOURCES, 2),
        *combinations(ALL_SOURCES, 3),
        *combinations(ALL_SOURCES, 4),
    ],
    ids=lambda s: " + ".join(s),
)
def test_fetch_all_with_explicit_sources(multi_fetcher, expected, sources):
    sources = set(sources)
    actual = multi_fetcher.fetch_all(sources=sources)
    assert set(actual) == sources

    for source in sources:
        assert actual[source] == expected[source], f"{source=}"


def test_fetch(multi_fetcher: MultiFetcher[str, int], data: dict[str, pd.DataFrame]) -> None:
    required = {"id"}
    placeholders = {"name", "is_nice"}

    sampled = [IdsToFetch(source, set(df.id)) for source, df in data.items()]
    memory_fetcher: MemoryFetcher[str, int] = MemoryFetcher(data)
    expected: SourcePlaceholderTranslations[str] = memory_fetcher.fetch(sampled, placeholders, required=required)
    actual = multi_fetcher.fetch(sampled, placeholders, required=required)

    assert actual == expected


def test_ranks(multi_fetcher, fetchers):
    default_fetcher, empty_fetcher, fallback_fetcher, sql_fetcher = fetchers

    assert len(multi_fetcher.children) == 3
    assert default_fetcher in multi_fetcher.children
    assert empty_fetcher not in multi_fetcher.children
    assert fallback_fetcher in multi_fetcher.children
    assert sql_fetcher in multi_fetcher.children

    assert multi_fetcher._id_to_rank[id(default_fetcher)] == 0
    assert multi_fetcher._id_to_rank[id(fallback_fetcher)] == 2
    assert multi_fetcher._id_to_rank[id(sql_fetcher)] == 3


def test_from_config():
    translator = Translator[str, str, IdTypes].from_config(
        ROOT / "config.imdb.toml",
        extra_fetchers=[ROOT / "transform/fetcher-only.toml"],
    )
    assert sorted(translator.sources) == ["drinking_preferences_bitmask", "guests", "name_basics", "title_basics"]


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
        fetcher = MultiFetcher(*children, on_source_conflict="ignore")

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

        ends = {
            "does not provide any sources.",
            "but will be kept: All sources found in higher-ranking fetchers.",
        }
        for record in caplog.records:
            message = record.getMessage()
            for end in ends:
                if message.endswith(end):
                    assert message.startswith("Required rank-0")
                    assert record.levelname == "WARNING"
                    assert record.name.endswith("MultiFetcher")
                    ends.remove(end)
                    break

    @pytest.mark.parametrize("level", ["DEBUG", "WARNING"])
    def test_optional(self, caplog, level):
        fetcher: MultiFetcher[str, int] = MultiFetcher(
            MemoryFetcher({}, optional=True), fetcher_discarded_log_level=level
        )
        fetcher.initialize_sources()

        assert len(fetcher.children) == 0

        for record in caplog.records:
            message = record.getMessage()

            if message.startswith("Discarding optional rank-0"):
                assert message.endswith("No sources.")
                assert record.levelname == level
                assert record.name.endswith("MultiFetcher")
                return

        raise AssertionError("no matching record found")


@pytest.mark.filterwarnings("ignore:Discarded:id_translation.fetching.exceptions.DuplicateSourceWarning")
def test_copy(fetchers):
    ids_to_fetch = [IdsToFetch("animals", {1})]

    not_cloneable = NotCloneableFetcher()
    original = MultiFetcher(not_cloneable, *fetchers, on_source_conflict="ignore", max_workers=2)
    original.initialize_sources()
    original_fetch_all = original.fetch_all()
    original_fetch = original.fetch(ids_to_fetch)

    copied = deepcopy(original)
    assert original_fetch_all == copied.fetch_all()
    assert original.placeholders == copied.placeholders

    copied_children = {copied._id_to_rank[id(c)]: id(c) for c in copied.children}
    original_children = {original._id_to_rank[id(c)]: id(c) for c in original.children}

    assert sorted(copied_children) == sorted(original_children), "keys should match"
    assert copied_children.pop(0) == original_children.pop(0), "NotCloneableFetcher - IDs should be same"
    assert copied_children != original_children, "IDs should be different"

    assert original_fetch == copied.fetch(ids_to_fetch)


def test_init_logging(multi_fetcher, caplog):
    assert len(caplog.records) == 0

    multi_fetcher.initialize_sources(id(test_init_logging))

    def discard_empty_optional(message: str, level: int) -> bool:
        if message.startswith("Discarding optional rank-1 fetcher MemoryFetcher(sources=<no sources>"):
            assert level == logging.DEBUG, "optional => DEBUG"
            assert message.endswith(": No sources.")
            return True

        return False

    def required_no_sources(message: str, level: int) -> bool:
        if message.startswith("Required rank-3 fetcher SqlFetcher('sqlite://')"):
            assert level == logging.WARNING, "required => WARNING"
            assert message.endswith("does not provide any sources.")
            return True

        return False

    def optional_source_outranked(message: str, level: int) -> bool:
        if message.startswith("Discarded source='humans' retrieved from rank-2 fetcher MemoryFetcher"):
            assert level == logging.DEBUG, "optional => DEBUG"
            assert "since the rank-0 fetcher MemoryFetcher(sources=['humans', 'animals']" in message
            assert "already claimed same source." in message
            return True

        return False

    checkers = [
        discard_empty_optional,
        required_no_sources,
        optional_source_outranked,
    ]

    index = 0
    for record in caplog.records:
        if index == len(checkers):
            return  # All checkers done
        if checkers[index](record.getMessage(), record.levelno):
            index += 1

    if index < len(checkers):
        raise AssertionError(f"Did not finish: {index=} | checker={checkers[index - 1]}")
