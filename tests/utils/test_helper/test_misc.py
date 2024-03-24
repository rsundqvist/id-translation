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

    helper.apply(1, inplace=False, user_params=True)
    name_to_source = helper.name_to_source()
    assert name_to_source == {"h": "h"}
    assert translator.translated_names(True) == {"h": "h"}

    translator.translate(1, names="t")
    name_to_source = helper.name_to_source()
    assert name_to_source == {"h": "h"}
    assert translator.translated_names(True) == {"t": "t"}
