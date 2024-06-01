from typing import Any, assert_type

from id_translation import Translator
from id_translation.utils.translation_helper import TranslationHelper

helper = TranslationHelper[str, str, int](Translator(), names="source")


class TestTrue:
    def test_inplace_true(self):
        result = helper.apply([1], copy=False, user_params=True)
        assert_type(result, None)

    def test_inplace_false_anonymous(self):
        result = helper.apply([1], copy=True, user_params=True)
        assert_type(result, list[str])  # type: ignore[assert-type]  # this is what we actually want
        assert_type(result, Any)  # this is what we know we get

    def test_inplace_false_reassigned(self):
        result = [1]
        result = helper.apply(result, copy=True, user_params=True)
        assert_type(result, list[str])  # type: ignore[assert-type]  # this is what we actually want
        assert_type(result, list[int])  # this is what we know we get - WRONG


class TestFalse:
    def test_inplace_true(self):
        result = helper.apply([1], copy=False, user_params=False)
        assert_type(result, None)

    def test_inplace_false(self):
        result = helper.apply([1], copy=True, user_params=False)
        assert_type(result, list[int])
