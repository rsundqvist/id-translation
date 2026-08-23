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


def check_status(dialect: str) -> None:
    """Friendly connectivity guard, mirroring ``tests/dvdrental/conftest.py::check_status``.

    This module ships standalone (see ``tests/dvdrental/docker/Dockerfile``) and cannot import from the main
    ``tests/dvdrental/`` package, hence the duplication.
    """
    connection_string = CONNECTION_STRING.format(dialect=dialect, driver=DRIVERS[dialect], **CREDENTIALS[dialect])

    try:
        with sqlalchemy.create_engine(connection_string).connect() as conn:
            next(conn.execute(sqlalchemy.text("SELECT 1")))
    except Exception:
        msg = (
            f"Unable to connect to database for {dialect=}. Start the databases"
            " by running:\n    ./run-docker-dvdrental.sh"
        )
        raise RuntimeError(msg) from None


def execute_query(dialect: str) -> pd.DataFrame:
    check_status(dialect)
    connection_string = CONNECTION_STRING.format(dialect=dialect, driver=DRIVERS[dialect], **CREDENTIALS[dialect])

    with sqlalchemy.create_engine(connection_string).connect() as conn:
        records = list(conn.execute(sqlalchemy.text(QUERY)))

    columns = ["customer_id", "film_id", "category_id", "staff_id", "rental_date", "return_date"]
    return pd.DataFrame.from_records(records, columns=columns)


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


def test_check_status_reports_friendly_error_when_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies the guard itself, by pointing at a dead port instead of stopping the real containers."""
    monkeypatch.setitem(CREDENTIALS["mysql"], "port", 1)  # Nothing listens here.
    with pytest.raises(
        RuntimeError,
        match=r"Unable to connect to database for dialect='mysql'\. Start the databases"
        r" by running:\n    \./run-docker-dvdrental\.sh",
    ):
        check_status("mysql")
