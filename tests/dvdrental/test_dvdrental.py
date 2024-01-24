from pathlib import Path

import pandas as pd
import pytest

from id_translation import Translator

from .conftest import DIALECTS, LINUX_ONLY, check_status, get_df, setup_for_dialect

pytestmark = [pytest.mark.parametrize("dialect", DIALECTS), LINUX_ONLY]


@pytest.mark.parametrize("with_schema", [False, True])
def test_dvd_rental(dialect, with_schema):
    check_status(dialect)
    translator: Translator[str, str, int] = Translator.from_config(*setup_for_dialect(dialect))

    sql_fetcher = translator.fetcher.children[1]  # type: ignore[attr-defined]
    assert sql_fetcher._schema is None
    if with_schema:
        sql_fetcher._schema = {"mysql": "sakila", "postgresql": "public", "mssql": "dbo"}[dialect]

    expected = pd.read_csv(
        Path(__file__).with_name("translated.csv"), index_col=0, parse_dates=["rental_date", "return_date"]
    )
    actual = get_df(dialect).loc[expected.index]
    assert translator.translate(actual, inplace=True) is None
    pd.testing.assert_frame_equal(actual, expected)


def test_load_persistent_instance(tmp_path, dialect):
    translator: Translator[str, str, int]
    cfg = setup_for_dialect(dialect)

    expected_metadata = Translator.load_persistent_instance(tmp_path, *cfg).config_metadata
    actual_metadata = Translator.load_persistent_instance(tmp_path, *cfg).config_metadata
    assert expected_metadata == actual_metadata
