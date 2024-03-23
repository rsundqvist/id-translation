import pandas as pd
import pytest
from id_translation.dio._pandas import PandasIO
from id_translation.dio.exceptions import NotInplaceTranslatableError


def test_pandas():
    dio = PandasIO

    with pytest.raises(NotInplaceTranslatableError, match="Index"):
        dio.insert(pd.Index([]), names=None, tmap=None, copy=False)  # type: ignore[arg-type]
