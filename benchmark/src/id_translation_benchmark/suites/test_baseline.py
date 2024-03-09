import pandas as pd
import pytest

from id_translation_benchmark.support import make_expected, prepare
from id_translation_benchmark.types import IdFactories, IdType, TranslatableT


@pytest.mark.parametrize("id_type", IdFactories)
@pytest.mark.parametrize("translatable_type", [pd.Series, pd.Index, list, tuple, set, dict])
@pytest.mark.parametrize("count", [1, 5, 25, 5_000])
def test_baseline(count: int, id_type: IdType, translatable_type: type[TranslatableT]):
    translatable, translator = prepare(count, id_type=id_type, translatable_type=translatable_type)
    actual = translator.translate(translatable, names="source", maximal_untranslated_fraction=0)

    expected = make_expected(count, id_type=id_type, translatable_type=translatable_type)

    try:
        assert actual == expected
    except ValueError:
        assert all(actual == expected)
