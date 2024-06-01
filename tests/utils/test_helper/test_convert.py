import pytest
from id_translation import Translator
from id_translation.utils.translation_helper import TranslationHelper

helper = TranslationHelper[str, str, int](Translator, user_params_name="test_convert", names="source")


def test_false():
    with pytest.raises(TypeError, match="convert test_convert=False"):
        helper.convert_user_params(False)


def test_true():
    assert helper.convert_user_params(True) == {}


def test_str():
    assert helper.convert_user_params("foo") == {"fmt": "foo"}


@pytest.mark.parametrize("value", [0.0, 0])
def test_max_fails(value):
    assert helper.convert_user_params(value) == {"max_fails": 0.0}


def test_unknown():
    with pytest.raises(TypeError, match="test_convert"):
        helper.convert_user_params([])  # type: ignore[arg-type]
