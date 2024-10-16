from copy import deepcopy

import pandas as pd
import pytest
import sqlalchemy

from id_translation.fetching import SqlFetcher as RealSqlFetcher
from id_translation.fetching import exceptions
from id_translation.fetching.exceptions import FetcherWarning
from id_translation.fetching.types import FetchInstruction, IdsToFetch
from id_translation.mapping import Mapper

ALL_TABLES = {"animals", "humans", "big_table", "huge_table"}

SqlFetcher = RealSqlFetcher[int]


@pytest.mark.parametrize("table_to_verify", ["animals", "humans", "big_table", "huge_table"])
def test_fetch_all(sql_fetcher, data, table_to_verify):
    translations = sql_fetcher.fetch_all(["id", "name", "is_nice", "gender"], required=["id"])

    actual = pd.DataFrame.from_dict(translations[table_to_verify].to_dict())
    expected = data[table_to_verify][actual.columns]

    pd.testing.assert_frame_equal(actual, expected)


def test_select_where_fetch_all(sql_fetcher, monkeypatch):
    original = sql_fetcher.select_where

    def select_where(*args, **kwargs):
        actual = original(*args, **kwargs)
        assert str(actual) == "SELECT huge_table.id \nFROM huge_table"
        return actual

    monkeypatch.setattr(sql_fetcher, "select_where", select_where)
    instr: FetchInstruction[str, int] = FetchInstruction("huge_table", ("id",), {"id"}, None, -1, False)
    ans = sql_fetcher.fetch_translations(instr).records
    assert ans == tuple((e,) for e in range(1000))


@pytest.mark.parametrize(
    "query_match, ids_to_fetch, expected",
    [
        ("WHERE false", [], []),
        ("WHERE huge_table.id IN ", [1, 200, 500], [1, 200, 500]),  # less than 100
        ("WHERE huge_table.id IN ", range(0, 1001, 5), range(0, 1000, 5)),  # count < 100, factor > 2.5 -> BETWEEN
        ("WHERE huge_table.id BETWEEN ", range(0, 1001, 2), range(1000)),  # count>100, factor < 2.5 -> BETWEEN
    ],
)
def test_select_where(ids_to_fetch, expected, query_match, sql_fetcher, monkeypatch):
    original = sql_fetcher.select_where

    def select_where(*args, **kwargs):
        actual = original(*args, **kwargs)
        assert query_match in str(actual)
        return actual

    monkeypatch.setattr(sql_fetcher, "select_where", select_where)
    instr = FetchInstruction("huge_table", ("id",), {"id"}, set(ids_to_fetch), -1, False)
    ans = sql_fetcher.fetch_translations(instr).records
    assert ans == tuple((e,) for e in expected)


@pytest.fixture(scope="module")
def sql_fetcher(connection_string):
    fetcher = SqlFetcher(connection_string)
    assert sorted(fetcher.sources) == ["animals", "big_table", "huge_table", "humans"]  # Forces initialization
    yield fetcher
    fetcher.close()


@pytest.fixture(scope="module")
def connection_string(data, windows_hack_temp_dir):
    db_file = windows_hack_temp_dir / "sql-fetcher-data"
    db_file.mkdir(parents=True, exist_ok=True)
    connection_string = f"sqlite:///{db_file.joinpath('db.sqlite')}"
    insert_data(connection_string, data)
    yield connection_string


def insert_data(connection_string, data):
    engine = sqlalchemy.create_engine(connection_string)
    for table, table_data in data.items():
        table_data.to_sql(table, engine, index=False)
    engine.dispose()


@pytest.mark.parametrize(
    "whitelist, expected",
    [
        (None, ALL_TABLES),
        (ALL_TABLES, ALL_TABLES),
        (["animals", "humans"], {"animals", "humans"}),
    ],
)
def test_whitelist(connection_string, whitelist, expected):
    fetcher = SqlFetcher(connection_string, whitelist_tables=whitelist)
    assert set(fetcher.sources) == expected
    fetcher.close()


def test_empty_whitelist(connection_string):
    with pytest.warns(FetcherWarning, match="empty"):
        fetcher = SqlFetcher(connection_string, whitelist_tables=())
        assert tuple(fetcher.sources) == ()
    fetcher.close()


@pytest.mark.parametrize("use_override", [False, True])
def test_unmappable_whitelist_table(use_override, connection_string):
    def score_fn(value, candidates, context):
        return ([0] * len(candidates)) if context == "big_table" else [float(value == c) for c in candidates]

    mapper = Mapper(
        score_fn,
        overrides={"id": "bad-column"} if use_override else None,
        filter_functions=[("filter_placeholders", dict(regex="", remove=True))],
    )

    fetcher = SqlFetcher(connection_string, mapper=mapper, whitelist_tables=["animals", "big_table", "huge_table"])

    with pytest.raises(exceptions.UnknownPlaceholderError, match="whitelist") as e:
        fetcher._get_summaries(-1)
    fetcher.close()
    assert ("'id' -> 'bad-column'" in str(e.value)) is use_override


@pytest.mark.parametrize("column", ["id", "name"])
def test_bad_override(column, connection_string):
    mapper: Mapper[str, str, str] = Mapper(overrides={column: "bad_column"})
    fetcher = SqlFetcher(connection_string, mapper=mapper)
    with pytest.raises(exceptions.UnknownPlaceholderError, match=repr(column)):
        fetcher.fetch([IdsToFetch("humans", {-1})], ("id", "name"), ("id", "name"))
    fetcher.close()


def test_deepcopy(connection_string):
    fetcher = SqlFetcher(
        connection_string,
        engine_kwargs={"hide_parameters": True, "execution_options": {"sqlite_raw_colnames": True}},
    )

    fetcher.initialize_sources()
    original_fetch_all = fetcher.fetch_all()
    ids_to_fetch = [IdsToFetch("animals", {1})]
    original_fetch = fetcher.fetch(ids_to_fetch)

    with pytest.raises(TypeError, match="cannot pickle"):
        deepcopy(fetcher.engine)
    cloned = deepcopy(fetcher)

    assert id(fetcher.engine) != id(cloned.engine)
    assert fetcher.engine.get_execution_options() == cloned.engine.get_execution_options()
    assert fetcher.engine.hide_parameters == cloned.engine.hide_parameters

    assert original_fetch_all == cloned.fetch_all()
    assert original_fetch == cloned.fetch(ids_to_fetch)
