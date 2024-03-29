from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest
from id_translation.dio import resolve_io

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

    actual: dict[str, Sequence[int]] = resolve_io(data).extract(data, names=["a"])
    assert len(actual) == 1
    assert sorted(actual["a"]) == sorted(VALUES)


@pytest.mark.parametrize("ttype", [list, tuple, pd.Index, pd.Series, np.array])
def test_sequence_extract_multiple_names(ttype):
    data = ttype(VALUES)
    actual: dict[str, Sequence[int]] = resolve_io(data).extract(data, names=NAMES)
    assert actual == {n: [v] for n, v in zip(NAMES, VALUES)}
