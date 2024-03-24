"""We want the type ignores here!

If they weren't needed, it would mean that there's a gap in the typing of the init-method.
"""

import pytest
from id_translation import Translator
from id_translation.utils.translation_helper import TranslationHelper

Helper = TranslationHelper[str, str, int]


def test_fixed_translatable():
    match = r"Found protected keys={'translatable'} in fixed_params={'translatable': None}."
    with pytest.raises(TypeError, match=match):
        Helper(Translator, translatable=None)  # type: ignore[call-arg]


def test_fixed_inplace():
    match = r"Found protected keys={'inplace'} in fixed_params={'inplace': None}."
    with pytest.raises(TypeError, match=match):
        Helper(Translator, inplace=None)  # type: ignore[call-arg]


def test_all():
    from id_translation.utils.translation_helper import ALWAYS_RESERVED

    kwargs = {k: None for k in ALWAYS_RESERVED}
    with pytest.raises(TypeError, match=str(set(ALWAYS_RESERVED))):
        Helper(Translator, **kwargs, fmt="")  # type: ignore[arg-type]
