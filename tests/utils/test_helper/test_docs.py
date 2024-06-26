from typing import Any

from id_translation import Translator
from id_translation.utils.translation_helper import TranslationHelper


def test_default():
    param = TranslationHelper(Translator).make_user_params_docstring()
    assert "'fmt'" in param
    assert "'max_fails'" in param


def test_fixed_fmt():
    helper: TranslationHelper[Any, Any, Any] = TranslationHelper(Translator, fmt="")

    param = helper.make_user_params_docstring()
    assert "'fmt'" not in param
    assert "'max_fails'" in param

    error = helper.make_type_error_docstring()
    assert "'fmt'" in error
    assert "'max_fails'" not in error
