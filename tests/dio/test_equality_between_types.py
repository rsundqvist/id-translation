import pandas as pd
import pytest

from .conftest import TRANSLATED, UNTRANSLATED


@pytest.mark.parametrize("ttype", [pd.DataFrame.from_dict, dict])
def test_translate_and_insert(imdb_translator, ttype):
    actual = imdb_translator.translate(ttype(UNTRANSLATED))

    if isinstance(actual, pd.DataFrame):
        actual = actual.to_dict(orient="list")

    assert actual == TRANSLATED
