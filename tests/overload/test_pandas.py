from typing import NoReturn, Union

import pandas as pd
from typing_extensions import assert_type

from id_translation import Translator

t: Translator[str, str, Union[int, str]] = Translator()
OutType = str

ID_TRANSLATION_PANDAS_IS_TYPED: bool = False  # pandas-stubs or similar


def type_frame() -> None:
    df = pd.DataFrame()

    assert_type(t.translate(df), "pd.DataFrame")
    assert_type(t.translate(df, inplace=False), "pd.DataFrame")

    if ID_TRANSLATION_PANDAS_IS_TYPED:
        assert_type(t.translate(df, inplace=True), None)


def type_series() -> None:
    series = pd.Series([1])

    assert_type(t.translate(series), "pd.Series[OutType]")
    assert_type(t.translate(series, inplace=False), "pd.Series[OutType]")
    if ID_TRANSLATION_PANDAS_IS_TYPED:
        assert_type(t.translate(series, inplace=True), None)


def type_index() -> None:
    index = pd.Index([1])

    assert_type(t.translate(index), "pd.Index[OutType]")
    assert_type(t.translate(index, inplace=False), "pd.Index[OutType]")
    if ID_TRANSLATION_PANDAS_IS_TYPED:
        assert_type(t.translate(index, inplace=True), NoReturn)
