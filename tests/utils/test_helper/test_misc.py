from functools import partial

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
    assert translator.translated_names() == {"h": "h"}

    translator.translate(1, names="t")
    name_to_source = helper.name_to_source()
    assert name_to_source == {"h": "h"}
    assert translator.translated_names() == {"t": "t"}


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


def _create_translator():
    return Translator[str, str, int]()


class _Factories:
    @classmethod
    def create(cls):
        return _create_translator()


@pytest.mark.parametrize(
    "translator_or_factory, expected",
    [
        (Translator[str, str, int](), "id_translation.Translator()"),
        (Translator, "id_translation.Translator"),
        (_create_translator, f"{__name__}._create_translator"),
        (_Factories.create, f"{__name__}._Factories.create"),
        (partial(_create_translator), f"partial({__name__}._create_translator)"),
        (
            partial(Translator.from_config, "config.toml", extra_fetchers=["more.toml"]),
            "partial(id_translation.Translator.from_config, 'config.toml', extra_fetchers=['more.toml'])",
        ),
        (
            partial(Translator, {"people": {i: f"name{i}" for i in range(50)}}),
            "partial(id_translation.Translator, dict)",
        ),
    ],
)
def test_repr(translator_or_factory, expected):
    assert repr(TranslationHelper(translator_or_factory)) == f"TranslationHelper({expected})"


def test_repr_multiline():
    helper = TranslationHelper[str, str, int](Translator, "params", names="name", fmt="{id}:{name}")
    assert repr(helper) == (
        "TranslationHelper(\n"
        "    id_translation.Translator,\n"
        "    user_params_name='params',\n"
        "    names='name',\n"
        "    fmt='{id}:{name}',\n"
        ")"
    )
