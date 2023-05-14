import pytest as pytest
import sqlalchemy

from id_translation.fetching import SqlFetcher, exceptions
from id_translation.fetching.exceptions import FetcherWarning
from id_translation.fetching.types import FetchInstruction, IdsToFetch
from id_translation.mapping import Mapper

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
    ans = sql_fetcher.fetch_translations(
        FetchInstruction(
            "huge_table",
            ("id",),
            {"id"},
            set(ids_to_fetch),
        )
    ).records
    assert ans == tuple((e,) for e in expected)


@pytest.fixture(scope="module")
def sql_fetcher(connection_string):
    fetcher = SqlFetcher(
        connection_string, fetch_in_below=25, fetch_between_over=500, fetch_between_max_overfetch_factor=2
    )
    yield fetcher
    fetcher.close()


@pytest.fixture(scope="module")
def connection_string(data, windows_hack_temp_dir):
    db_file = windows_hack_temp_dir.joinpath(windows_hack_temp_dir, "sql-fetcher-data")
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
        fetcher._get_summaries()
    fetcher.close()
    assert ("'id' -> 'bad-column'" in str(e.value)) is use_override


@pytest.mark.parametrize("column", ["id", "name"])
def test_bad_override(column, connection_string):
    mapper: Mapper[str, str, str] = Mapper(overrides={column: "bad_column"})
    fetcher = SqlFetcher(connection_string, mapper=mapper)
    with pytest.raises(exceptions.UnknownPlaceholderError, match=repr(column)):
        fetcher.fetch([IdsToFetch("humans", {-1})], (column,), (column,))  # Add ID to avoid fetch-all
    fetcher.close()


@pytest.mark.parametrize(
    "allow_fetch_all, fetch_all_limit, expected",
    [
        (False, 10000, False),
        (False, 0, False),
        (True, 0, False),
        (True, 2000, True),
        (True, 900, False),
    ],
)
def test_fetch_all_limit(connection_string, allow_fetch_all, fetch_all_limit, expected):
    assert (
        SqlFetcher(connection_string, allow_fetch_all=allow_fetch_all, fetch_all_limit=fetch_all_limit).allow_fetch_all
        == expected
    )
