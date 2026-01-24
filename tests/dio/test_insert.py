from collections.abc import Collection, Mapping
from typing import Any, TypeAlias

import numpy as np
import pandas as pd
import pytest

from id_translation.dio import DataStructureIO, resolve_io
from id_translation.dio.exceptions import NotInplaceTranslatableError
from id_translation.types import IdType, SourceType

from .conftest import TRANSLATED, UNTRANSLATED

NAME = "nconst"

CollectionOrStrDict = dict[str, IdType] | Mapping[str, IdType] | Collection[IdType]
DIO: TypeAlias = DataStructureIO[CollectionOrStrDict[IdType], str, SourceType, IdType]


def test_dict_insert(translation_map):
    expected = {"firstTitle": {TRANSLATED["firstTitle"][2]}, "nconst": TRANSLATED["nconst"].copy()}

    actual = {"firstTitle": {UNTRANSLATED["firstTitle"][2]}, "nconst": UNTRANSLATED["nconst"].copy()}
    dict_io: DIO[str, int] = resolve_io(actual)
    copied = dict_io.insert(actual, list(actual), translation_map, copy=True)
    assert copied == expected

    dict_io.insert(actual, list(actual), translation_map, copy=False)
    assert actual == expected


@pytest.mark.parametrize("ttype", [list, tuple, pd.Index, pd.Series, np.array])
def test_sequence_insert(ttype, translation_map):
    actual, ans = _do_insert(translation_map, ttype, copy=True)
    _test_eq(ans, ttype(TRANSLATED[NAME]))
    _test_eq(actual, ttype(UNTRANSLATED[NAME]))


@pytest.mark.parametrize("ttype", [list, set])
def test_sequence_insert_inplace(ttype, translation_map):
    actual = ttype(UNTRANSLATED[NAME])
    translatable_io: DataStructureIO[Any, str, str, str] = resolve_io(actual)
    ans = translatable_io.insert(actual, [NAME], translation_map, copy=False)
    assert ans is None
    _test_eq(actual, ttype(TRANSLATED[NAME]))


def test_insert_inplace_array(translation_map):
    actual = np.array(UNTRANSLATED[NAME], dtype=object)
    translatable_io: DataStructureIO[Any, str, str, str] = resolve_io(actual)
    ans = translatable_io.insert(actual, [NAME], translation_map, copy=False)
    assert ans is None
    _test_eq(actual, np.array(TRANSLATED[NAME]))


def test_forbidden_insert_inplace(translation_map):
    actual = tuple(UNTRANSLATED[NAME])
    translatable_io: DIO[int, str] = resolve_io(actual)

    with pytest.raises(NotInplaceTranslatableError):
        translatable_io.insert(actual, [NAME], translation_map, copy=False)


def test_large_series(translation_map, monkeypatch):
    from id_translation.offline import MagicDict

    num_getitem_calls = 0
    real_getitem = MagicDict.__getitem__

    def increment_call_count(self, key):
        nonlocal num_getitem_calls
        num_getitem_calls += 1
        return real_getitem(self, key)

    monkeypatch.setattr(MagicDict, "__getitem__", increment_call_count)

    large_list = UNTRANSLATED[NAME] * 1000
    large_series = pd.Series(large_list)

    list_io: DIO[int, str] = resolve_io(large_list)
    large_list_result = list_io.insert(large_list, [NAME], translation_map, copy=True)
    assert num_getitem_calls == len(large_list)  # Not actually needed; fewer would be nice!

    series_io: DIO[int, str] = resolve_io(large_series)
    large_series_result = series_io.insert(large_series, [NAME], translation_map, copy=True)
    assert large_series_result is not None
    assert num_getitem_calls == len(large_list) + large_series.nunique()

    assert TRANSLATED[NAME] * 1000 == large_list_result
    assert large_list_result == large_series_result.to_list()


def _do_insert(translation_map, ttype, copy):
    actual = ttype(UNTRANSLATED[NAME])
    translatable_io: DIO[int, str] = resolve_io(actual)
    ans = translatable_io.insert(actual, [NAME], translation_map, copy=copy)
    return actual, ans


def _test_eq(actual, expected):
    try:
        assert actual == expected
    except ValueError:
        assert all(actual == expected)
