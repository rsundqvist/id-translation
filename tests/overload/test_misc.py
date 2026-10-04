from typing import Any, assert_type

from id_translation import Translator
from id_translation.types import Translatable

t: Translator[str, str, Any] = Translator()
OutType = str


def type_list() -> None:
    expected = list[OutType]

    li = [1]
    assert_type(t.translate(li), expected)
    assert_type(t.translate(li, copy=True), expected)
    assert_type(t.translate(li, copy=False), None)

    ls = ["1"]
    assert_type(t.translate(ls), expected)
    assert_type(t.translate(ls, copy=True), expected)
    assert_type(t.translate(ls, copy=False), None)


def type_catch_all(
    translator: Translator[str, str, int], ids: Translatable[str, int], names: Translatable[str, str]
) -> None:
    assert_type(translator.translate(ids), Translatable[str, str])
    assert_type(translator.translate(ids, reverse=False), Translatable[str, str])
    assert_type(translator.translate(names, reverse=True), Translatable[str, int])


def type_set() -> None:
    expected = set[OutType]

    si = {1}
    assert_type(t.translate(si), expected)
    assert_type(t.translate(si, copy=True), expected)
    assert_type(t.translate(si, copy=False), None)

    ss = {"1"}
    assert_type(t.translate(ss), expected)
    assert_type(t.translate(ss, copy=True), expected)
    assert_type(t.translate(ss, copy=False), None)
