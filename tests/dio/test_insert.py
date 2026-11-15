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
    n_misses = 1  # id=500: direct hits are joined against MagicDict.real without per-id lookups.
    assert num_getitem_calls == len(large_list) + n_misses

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


@pytest.mark.parametrize(
    "array, stored",
    [
        (np.array([1, 2]), False),  # Not an object or string dtype; numpy would cast or refuse the translations.
        (np.array(["1", "2"]), False),  # <U1: numpy would truncate the translations.
        (np.array(["1", "2"], dtype="<U20"), True),
        (np.array(["1", "2"], dtype=object), True),
        (np.array(["1", "2"], dtype=np.dtypes.StringDType()), True),
    ],
)
def test_ndarray_inplace(array, stored):
    from id_translation import Translator

    translator: Translator[str, str, str] = Translator({"people": {"1": "Alice", "2": "Bob"}})

    if stored:
        assert translator.translate(array, names="people", copy=False) is None
        assert array.tolist() == ["1:Alice", "2:Bob"]
    else:
        before = array.copy()
        with pytest.raises(NotInplaceTranslatableError) as exc_info:
            translator.translate(array, names="people", copy=False)
        assert "Hint: Use copy=True, or an array with dtype=object." in exc_info.value.__notes__
        assert array.tolist() == before.tolist(), "unchanged"


def test_tuple_inplace():
    from id_translation import Translator

    translator: Translator[str, str, str] = Translator({"people": {"1": "Alice", "2": "Bob"}})

    with pytest.raises(NotInplaceTranslatableError) as exc_info:
        translator.translate(("1", "2"), names="people", copy=False)
    assert "Hint: Use copy=True." in exc_info.value.__notes__


@pytest.mark.parametrize(
    "array, stored",
    [
        (np.array([["1", "2"], ["2", "1"]], dtype="<U5"), False),  # Numpy would truncate the translations.
        (np.array([["1", "2"], ["2", "1"]], dtype="<U20"), True),
    ],
)
def test_ndarray_inplace_2d(array, stored):
    from id_translation import Translator

    translator: Translator[str, str, str] = Translator({"people": {"1": "Alice", "2": "Bob"}})
    names = ["people", "people"]

    if stored:
        assert translator.translate(array, names=names, copy=False) is None
        assert array.tolist() == [["1:Alice", "2:Bob"], ["2:Bob", "1:Alice"]]
    else:
        before = array.copy()
        with pytest.raises(NotInplaceTranslatableError):
            translator.translate(array, names=names, copy=False)
        assert array.tolist() == before.tolist(), "unchanged"


def test_bool_ndarray_inplace():
    from id_translation import Translator

    translator: Translator[str, str, bool] = Translator({"flags": {False: "no", True: "yes"}})
    array: Any = np.array([False, True])  # The overloads do not cover ndarray.

    with pytest.raises(NotInplaceTranslatableError):
        translator.translate(array, names="flags", copy=False)
    assert array.tolist() == [False, True], "unchanged; numpy would cast every translation to True"
