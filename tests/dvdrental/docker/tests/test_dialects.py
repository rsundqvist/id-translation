from os import getenv
from pathlib import Path
from sys import platform

import pandas as pd
import pytest
import sqlalchemy
import yaml  # type: ignore

if getenv("CI") == "true" and platform != "linux":
    pytest.skip("No Docker for Mac and Windows in CI/CD.", allow_module_level=True)

DIR = Path(__file__).parent
CREDENTIALS = yaml.safe_load(DIR.parent.joinpath("credentials.yml").read_text())["dialects"]
DIALECTS = list(CREDENTIALS)
CONNECTION_STRING = "{dialect}+{driver}://{user}:{password}@localhost:{port}/{database}"

QUERY = DIR.joinpath("query.sql").read_text()
DRIVERS = {
    "mysql": "pymysql",
    "postgresql": "pg8000",
    "mssql": "pymssql",
}


def execute_query(dialect: str) -> pd.DataFrame:
    connection_string = CONNECTION_STRING.format(dialect=dialect, driver=DRIVERS[dialect], **CREDENTIALS[dialect])
    return pd.read_sql(QUERY, sqlalchemy.create_engine(connection_string))


def test_reference() -> None:
    actual = execute_query("mysql")
    assert actual.shape == (16044, 6)

    expected = pd.read_csv(DIR.joinpath("expected.csv"), index_col=0, parse_dates=["rental_date", "return_date"])
    pd.testing.assert_frame_equal(actual.loc[expected.index], expected)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_equality(dialect: str, expected: pd.DataFrame) -> None:
    pd.testing.assert_frame_equal(execute_query(dialect), expected)


@pytest.fixture(scope="session")
def expected() -> pd.DataFrame:
    return execute_query("mysql")
