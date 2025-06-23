import pandas as pd
import pytest

from id_translation.dio.exceptions import NotInplaceTranslatableError
from id_translation.dio.integration.pandas import PandasIO


def test_pandas():
    with pytest.raises(NotInplaceTranslatableError, match="Index"):
        PandasIO.insert(pd.Index([]), names=None, tmap=None, copy=False)  # type: ignore[arg-type]
