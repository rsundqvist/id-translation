import os
import time
from os.path import join
from tempfile import TemporaryDirectory

import pytest as pytest
import sqlalchemy
from rics.collections.dicts import InheritedKeysDict
from rics.mapping import Mapper

from id_translation.fetching import SqlFetcher, exceptions
from id_translation.fetching.types import FetchInstruction, IdsToFetch

ALL_TABLES = {"animals", "humans", "big_table", "huge_table"}


def test_table_sizes(sql_fetcher):
    actual_sizes = {ts.name: ts.size for ts in sql_fetcher._get_summaries().values()}

    assert actual_sizes == {
        "animals": 3,
        "humans": 2,
        "big_table": 100,
        "huge_table": 1000,
    }


@pytest.mark.parametrize("table_to_verify", ["animals", "humans", "big_table", "huge_table"])
def test_fetch_all(sql_fetcher, data, table_to_verify):
    actual = sql_fetcher.fetch_all(["id", "name", "is_nice", "gender"], required=["id"])[table_to_verify].records
    expected = tuple(data[table_to_verify].to_records(False))

    actual_cast = tuple(tuple(r) for r in actual)
    expected_cast = tuple(tuple(r) for r in expected)

    assert actual_cast == expected_cast


@pytest.mark.parametrize(
    "ids_to_fetch, expected",
    [
        (range(600), range(600)),
        (range(950), range(1000)),
        (range(0, 1000, 5), range(0, 1000, 5)),
        (range(800, 900, 5), range(800, 900, 5)),
        (range(500, 1001, 2), range(500, 1000)),
    ],
    ids=[
        "FETCH_BETWEEN_SHORT_CIRCUIT",
        "FETCH_ALL_SHORT_CIRCUIT",
        "FETCH_IN_HEURISTIC",
        "FETCH_IN_SHORT_CIRCUIT",
        "FETCH_BETWEEN_HEURISTIC",
    ],
)
def test_heuristic(sql_fetcher, ids_to_fetch, expected):
    ans = sql_fetcher.fetch_translations(FetchInstruction("huge_table", ids_to_fetch, ("id",), {"id"}, False)).records
    assert ans == tuple((e,) for e in expected)


@pytest.fixture(scope="module")
def sql_fetcher(connection_string):
    fetcher = SqlFetcher(
        connection_string, fetch_in_below=25, fetch_between_over=500, fetch_between_max_overfetch_factor=2
    )
    yield fetcher
    fetcher.close()


@pytest.fixture(scope="module")
def connection_string(data):
    with TemporaryDirectory() as tmpdir:
        db_file = join(tmpdir, "sqlfetcher-test-database.sqlite")
        connection_string = f"sqlite:///{db_file}"
        insert_data(connection_string, data)
        yield connection_string
        if os.name == "nt":
            # Windows seems more sensitive to this. Sleep a while to make sure all engines close their connections.
            time.sleep(5)


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
    with pytest.warns(UserWarning, match="empty"):
        fetcher = SqlFetcher(connection_string, whitelist_tables=())
        assert tuple(fetcher.sources) == ()
    fetcher.close()


@pytest.mark.parametrize("column", ["id", "name"])
def test_bad_override(column, connection_string):
    mapper: Mapper[str, str, str] = Mapper(overrides=InheritedKeysDict(default={column: "bad_column"}))
    fetcher = SqlFetcher(connection_string, mapper=mapper)
    with pytest.raises(exceptions.UnknownPlaceholderError, match=f"'{column}': 'bad_column'"):
        fetcher.fetch([IdsToFetch("humans", None)], (column,), (column,))
    fetcher.close()
