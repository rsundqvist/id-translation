import pytest
from id_translation import Translator
from id_translation.utils.translation_helper import TranslationHelper

helper = TranslationHelper[str, str, int](Translator(), user_params_name="hierarchy", names="source")


def test_user_overrides_default():
    assert helper.apply(1, inplace=False, user_params="{title}", fmt="{name}") == "title-of-1"
    assert helper.apply(1, inplace=False, user_params="{name}", fmt="{title}") == "name-of-1"
    assert helper.apply(1, inplace=False, user_params=True) == "1:name-of-1"
    assert helper.apply(1, inplace=False, user_params={}) == "1:name-of-1"


def test_fixed_overrides_user():
    match = r"Found protected keys={'names'} in hierarchy={'names': None, 'fmt': ''}."
    with pytest.raises(TypeError, match=match):
        helper.apply(1, inplace=False, user_params={"names": None, "fmt": ""})


def test_fixed_overrides_default():
    match = r"Found protected keys={'names'} in default_params={'names': None}."
    with pytest.raises(TypeError, match=match):
        helper.apply(1, inplace=False, user_params=True, names=None)
