from typing import NoReturn, assert_type

import pandas as pd
from id_translation import Translator

t: Translator[str, str, int | str] = Translator()
OutType = str

ID_TRANSLATION_PANDAS_IS_TYPED: bool = False  # pandas-stubs or similar


def type_frame() -> None:
    df = pd.DataFrame()

    assert_type(t.translate(df), "pd.DataFrame")
    assert_type(t.translate(df, copy=True), "pd.DataFrame")

    if ID_TRANSLATION_PANDAS_IS_TYPED:
        assert_type(t.translate(df, copy=False), None)


def type_series() -> None:
    series = pd.Series([1])

    assert_type(t.translate(series), "pd.Series[OutType]")
    assert_type(t.translate(series, copy=True), "pd.Series[OutType]")
    if ID_TRANSLATION_PANDAS_IS_TYPED:
        assert_type(t.translate(series, copy=False), None)


def type_index() -> None:
    index = pd.Index([1])

    assert_type(t.translate(index), "pd.Index[OutType]")
    assert_type(t.translate(index, copy=True), "pd.Index[OutType]")
    if ID_TRANSLATION_PANDAS_IS_TYPED:
        assert_type(t.translate(index, copy=False), NoReturn)
