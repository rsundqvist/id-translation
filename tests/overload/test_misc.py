from typing import Any, List, Set

from typing_extensions import assert_type

from id_translation import Translator

t: Translator[str, str, Any] = Translator()
OutType = str


def type_list() -> None:
    expected = List[OutType]

    li = [1]
    assert_type(t.translate(li), expected)
    assert_type(t.translate(li, inplace=False), expected)
    assert_type(t.translate(li, inplace=True), None)

    ls = ["1"]
    assert_type(t.translate(ls), expected)
    assert_type(t.translate(ls, inplace=False), expected)
    assert_type(t.translate(ls, inplace=True), None)


# This doesn't seem to work; nested generic type issue?
# TODO Need Higher-Kinded TypeVars?
# def type_list_of_lists() -> None:
#     expected = List[List[OutType]]
#
#     lli = [[1]]
#     assert_type(t.translate(lli), expected)
#     assert_type(t.translate(lli, inplace=False), expected)
#     assert_type(t.translate(lli, inplace=True), None)
#
#     lls = ["1"]
#     assert_type(t.translate(lls), expected)
#     assert_type(t.translate(lls, inplace=False), expected)
#     assert_type(t.translate(lls, inplace=True), None)


def type_set() -> None:
    expected = Set[OutType]

    si = {1}
    assert_type(t.translate(si), expected)
    assert_type(t.translate(si, inplace=False), expected)
    assert_type(t.translate(si, inplace=True), None)

    ss = {"1"}
    assert_type(t.translate(ss), expected)
    assert_type(t.translate(ss, inplace=False), expected)
    assert_type(t.translate(ss, inplace=True), None)
