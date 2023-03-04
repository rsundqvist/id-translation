from itertools import product
from os import getenv
from pathlib import Path
from sys import platform

import pandas as pd
import pytest
import sqlalchemy

from id_translation import Translator

from .conftest import DIALECTS, QUERY, check_status, get_connection_string, setup_for_dialect

pytestmark = pytest.mark.skipif(
    getenv("CI") == "true" and platform != "linux", reason="No Docker for Mac and Windows in CI/CD."
)


@pytest.mark.parametrize("dialect, with_schema", product(DIALECTS, [False, True]))
def test_dvd_rental(dialect, with_schema):
    check_status(dialect)
    engine = sqlalchemy.create_engine(get_connection_string(dialect))
    translator: Translator[str, str, int] = Translator.from_config(*setup_for_dialect(dialect))

    sql_fetcher = translator.fetcher.fetchers[1]  # type: ignore[attr-defined]
    assert sql_fetcher._schema is None
    if with_schema:
        sql_fetcher._schema = {"mysql": "sakila", "postgresql": "public", "mssql": "dbo"}[dialect]

    expected = pd.read_csv(
        Path(__file__).with_name("translated.csv"), index_col=0, parse_dates=["rental_date", "return_date"]
    )
    with engine.connect() as conn:
        records = list(conn.execute(sqlalchemy.text(QUERY)))
    df = pd.DataFrame.from_records(records, columns=expected.columns).loc[expected.index]
    actual = translator.translate(df)

    assert actual is not None
    pd.testing.assert_frame_equal(actual, expected)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_load_persistent_instance(tmp_path, dialect):
    translator: Translator[str, str, int]
    cfg = setup_for_dialect(dialect)

    expected_metadata = Translator.load_persistent_instance(tmp_path, *cfg).config_metadata
    actual_metadata = Translator.load_persistent_instance(tmp_path, *cfg).config_metadata
    assert expected_metadata == actual_metadata
