import numpy as np
import pandas as pd
import pytest

from id_translation.dio.exceptions import NotInplaceTranslatableError
from id_translation.dio.integration.pandas import PandasIO as _PandasIO
from id_translation.dio.integration.pandas import PandasT
from id_translation.offline import TranslationMap
from id_translation.offline.types import PlaceholderTranslations

PandasIO = _PandasIO[PandasT, str, str, int | str]
del _PandasIO


class TestMissingAsNan:
    @classmethod
    def insert(cls, translatable: PandasT, tmap: TranslationMap[str, str, int | str], names: list[str]) -> None:
        io = PandasIO[PandasT](missing_as_nan=True)
        io.insert(translatable, names, tmap, copy=False)

    def test_series(self, tmap):
        series = pd.Series(["1", float("nan")])
        self.insert(series, tmap, names=["str_source"])
        assert series.to_dict() == {0: "'1':One", 1: np.nan}

    def test_frame(self, tmap):
        df = pd.Series(["1", float("nan")]).to_frame("str_source")
        self.insert(df, tmap, names=["str_source"])
        assert df.to_dict() == {"str_source": {0: "'1':One", 1: np.nan}}

    def test_single_repeated_name(self, tmap):
        series = pd.Series(["1", float("nan")])
        self.insert(series, tmap, names=["str_source", "str_source"])
        assert series.to_dict() == {0: "'1':One", 1: np.nan}

    def test_different_names(self, tmap):
        series = pd.Series(list("ab"))

        with pytest.raises(NotImplementedError, match=r"missing_as_nan=True.*names=\['a', 'b'\]"):
            self.insert(series, tmap, names=["a", "b"])


class TestInplace:
    def test_index(self, tmap):
        index = pd.Index([])
        with pytest.raises(NotInplaceTranslatableError, match="Index"):
            PandasIO[pd.Index]().insert(index, names=[], tmap=tmap, copy=False)

    def test_series_int(self, tmap):
        source = "int_source"
        series = pd.Series([1], name=source)

        with pytest.raises(NotInplaceTranslatableError, match="Series"):
            PandasIO[pd.Series]().insert(series, names=[source], tmap=tmap, copy=False)

        assert series[0] == 1

    def test_series_str(self, tmap):
        source = "str_source"
        series = pd.Series(["1"], name=source)
        result = PandasIO[pd.Series]().insert(series, names=[source], tmap=tmap, copy=False)
        assert result is None
        assert series[0] == "'1':One"


@pytest.fixture
def tmap() -> TranslationMap[str, str, int | str]:
    int_source = PlaceholderTranslations.from_dict("int_source", {1: "One"})
    str_source = PlaceholderTranslations.from_dict("str_source", {"1": "One"})
    source_translations = {
        int_source.source: int_source,
        str_source.source: str_source,
    }
    return TranslationMap(source_translations, fmt="{id!r}:{name}")
