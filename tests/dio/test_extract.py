from enum import IntEnum
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest

from id_translation import Translator
from id_translation.dio import DataStructureIO, resolve_io
from id_translation.exceptions import MissingNamesError
from id_translation.fetching import MemoryFetcher

if TYPE_CHECKING:
    from collections.abc import Sequence

NAMES = list("abcd")
VALUES = [3, 1, 5, 6]


@pytest.mark.parametrize("ttype", [set, list, tuple, pd.Index, pd.Series, np.array])
def test_extract_single_explicit_name(ttype):
    try:
        data = ttype(VALUES, name="not-a")
    except TypeError:
        data = ttype(VALUES)

    io: DataStructureIO[dict[str, Sequence[int]], str, str, int] = resolve_io(data)
    actual = io.extract(data, names=["a"])
    assert len(actual) == 1
    assert sorted(actual["a"]) == sorted(VALUES)


@pytest.mark.parametrize("ttype", [list, tuple, pd.Index, pd.Series, np.array])
def test_sequence_extract_multiple_names(ttype):
    data = ttype(VALUES)
    io: DataStructureIO[Sequence[int], str, str, int] = resolve_io(data)
    actual = io.extract(data, names=NAMES)
    assert actual == {n: [v] for n, v in zip(NAMES, VALUES, strict=True)}


@pytest.mark.parametrize("ttype", [list, tuple])
def test_sequence_extract_repeated_names(ttype):
    io: DataStructureIO[Sequence[Sequence[int]], str, str, int] = resolve_io(ttype([[1, 2], [3], [4]]))
    actual = io.extract(ttype([[1, 2], [3], [4]]), names=["a", "b", "a"])
    assert actual == {"a": [1, 2, 4], "b": [3]}


def test_repeated_names_online():
    translator: Translator[str, str, int] = Translator(MemoryFetcher({"a": {"id": [1, 2], "name": ["one", "two"]}}))
    assert translator.translate([[1], [2]], names=["a", "a"]) == [["1:one"], ["2:two"]]


def test_scalar_name_attribute_is_not_a_name():
    class People(IntEnum):
        FRED = 1904

    with pytest.raises(MissingNamesError):
        Translator({"people": {1904: "Fred"}}).translate(People.FRED)
