import pytest

from id_translation import Translator
from id_translation.utils.translation_helper import TranslationHelper


def test_translated_names():
    translator = Translator[str, str, int]()
    with pytest.raises(ValueError, match="Translator"):
        translator.translated_names()

    helper = TranslationHelper(translator, names="h")
    with pytest.raises(ValueError, match="TranslationHelper"):
        helper.name_to_source()

    helper.apply(1, copy=True, user_params=True)
    name_to_source = helper.name_to_source()
    assert name_to_source == {"h": "h"}
    assert translator.translated_names(True) == {"h": "h"}

    translator.translate(1, names="t")
    name_to_source = helper.name_to_source()
    assert name_to_source == {"h": "h"}
    assert translator.translated_names(True) == {"t": "t"}


def test_translation_disabled_passes_through(monkeypatch):
    from id_translation._translator import ID_TRANSLATION_DISABLED
    from id_translation.exceptions import TranslationDisabledWarning

    monkeypatch.setenv(ID_TRANSLATION_DISABLED, "true")
    helper = TranslationHelper(Translator[str, str, int](), names="h")
    data = {"h": [1]}

    with pytest.warns(TranslationDisabledWarning):
        assert helper.apply(data, copy=True, user_params=True) is data

    with pytest.raises(ValueError, match="TranslationHelper"):
        helper.name_to_source()
