import pandas as pd
import pytest

from id_translation.dio.exceptions import NotInplaceTranslatableError
from id_translation.dio.integration.pandas import PandasIO
from id_translation.offline import TranslationMap
from id_translation.offline.types import PlaceholderTranslations


class TestInplace:
    def test_index(self, tmap):
        index = pd.Index([])
        with pytest.raises(NotInplaceTranslatableError, match="Index"):
            PandasIO.insert(index, names=None, tmap=tmap, copy=False)  # type: ignore[arg-type]

    def test_series_int(self, tmap):
        source = "int_source"
        series = pd.Series([1], name=source)

        with pytest.raises(NotInplaceTranslatableError, match="Series"):
            PandasIO.insert(series, names=[source], tmap=tmap, copy=False)

        assert series[0] == 1

    def test_series_str(self, tmap):
        source = "str_source"
        series = pd.Series(["1"], name=source)
        result = PandasIO.insert(series, names=[source], tmap=tmap, copy=False)
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
