from itertools import product
from os import getenv
from sys import platform
from typing import Any
from uuid import UUID

import pandas as pd
import pytest
from rics.misc import tname

from id_translation import Translator
from id_translation.fetching import SqlFetcher
from id_translation.mapping import Mapper

from .conftest import DIALECTS, check_status, get_connection_string

pytestmark = pytest.mark.skipif(
    getenv("CI") == "true" and platform != "linux", reason="No Docker for Mac and Windows in CI/CD."
)

EXPECTED = {
    "3F333DF6-90a4-4fda-8dd3-9485d27cee36": "mixed",
    "6ecd8c99-4036-403d-bf84-cf8400f67836": "lower",
    "40E6215D-B5C6-4896-987C-F30F3678F608": "upper",
}
EXPECTED_NUM_OK = {
    ("mysql", False): 1,
    ("mysql", True): 4,
    ("postgresql", False): 2,
    ("postgresql", True): 8,
    ("mssql", False): 2,
    ("mssql", True): 8,
}
TABLE_NAME = "uuid_test_table"


@pytest.mark.parametrize("dialect, enable_uuid_heuristics", product(DIALECTS, [False, True]))
def test_uuid_migrations(dialect: str, enable_uuid_heuristics: bool) -> None:
    check_status(dialect)

    expected = list(EXPECTED.values())

    records = []
    for id_column in "uuid", "str_uuid":
        t: Translator[str, str, Any] = Translator(
            make_fetcher(dialect, id_column),
            fmt="{name}",
            enable_uuid_heuristics=enable_uuid_heuristics,
        )
        assert t.sources == [TABLE_NAME], t.sources

        for id_type in str, str.lower, str.upper, UUID:
            res: Any
            translatable = list(map(id_type, EXPECTED))  # type: ignore[call-overload]
            res = t.translate(translatable, names=TABLE_NAME)

            records.append(
                dict(
                    id_column=id_column,
                    id_type=tname(id_type),
                    output=res,
                    num_correct=sum(actual == expected for actual, expected in zip(res, expected)),
                    ok=res == expected,
                )
            )
    df = pd.DataFrame.from_records(records)
    df[["enable_uuid_heuristics", "dialect"]] = enable_uuid_heuristics, dialect
    print(f"Result: {df['num_correct'].sum()}/{len(df)*len(expected)} correct:\n{df}")
    num_ok = df["ok"].sum()
    expected_num_ok = EXPECTED_NUM_OK[(dialect, enable_uuid_heuristics)]
    assert num_ok >= expected_num_ok, "Regression!"
    assert num_ok == expected_num_ok, "Improvement!"
    if enable_uuid_heuristics and dialect != "mysql":  # MySql uses a binary uuid-column (no "real" uuid type exists").
        assert df["ok"].all()


def make_fetcher(dialect: str, id_column: str) -> SqlFetcher[Any]:
    return SqlFetcher(
        get_connection_string(dialect),
        mapper=Mapper(overrides={"id": id_column, "name": "comment"}),
        whitelist_tables=[TABLE_NAME],
    )
