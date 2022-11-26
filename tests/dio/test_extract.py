import numpy as np
import pandas as pd
import pytest

from id_translation.dio import resolve_io

NAMES = list("abcd")
VALUES = [3, 1, 5, 6]


@pytest.mark.parametrize("ttype", [list, tuple, pd.Index, pd.Series, np.array])
def test_sequence_extract(ttype):
    data = ttype(VALUES)
    actual = resolve_io(data).extract(data, names=NAMES)
    assert actual == {n: [v] for n, v, in zip(NAMES, VALUES)}
