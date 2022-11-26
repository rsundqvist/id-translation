from os import getenv
from pathlib import Path
from sys import platform

import pandas as pd
import pytest
import sqlalchemy

from .conftest import QUERY, check_status, get_connection_string, get_translator

DIALECTS = [
    "mysql",
    "postgresql",
    "mssql",  # Quite slow, mostly since the (pyre-python) driver used doesn't support fast_executemany
]


@pytest.mark.filterwarnings("ignore:Did not recognize type:sqlalchemy.exc.SAWarning")
@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.skipif(getenv("CI") == "true" and platform != "linux", reason="No Docker for Mac and Windows in CI/CD.")
def test_dvd_rental(dialect):
    check_status(dialect)
    engine = sqlalchemy.create_engine(get_connection_string(dialect))
    translator = get_translator(dialect)
    expected = pd.read_csv(
        Path(__file__).with_name("translated.csv"), index_col=0, parse_dates=["rental_date", "return_date"]
    )
    df: pd.DataFrame = pd.read_sql(QUERY, engine).loc[expected.index]
    actual = translator.translate(df)

    assert actual is not None
    pd.testing.assert_frame_equal(actual, expected)
