from typing import Any, assert_type

from id_translation import Translator

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


# This doesn't seem to work; nested generic type issue?
# TODO Need Higher-Kinded TypeVars?
# def type_list_of_lists() -> None:
#     expected = List[List[OutType]]
#
#     lli = [[1]]
#     assert_type(t.translate(lli), expected)
#     assert_type(t.translate(lli, copy=True), expected)
#     assert_type(t.translate(lli, copy=False), None)
#
#     lls = ["1"]
#     assert_type(t.translate(lls), expected)
#     assert_type(t.translate(lls, copy=True), expected)
#     assert_type(t.translate(lls, copy=False), None)


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
