from typing import NoReturn, assert_type

from id_translation import Translator

t: Translator[str, str, int | str] = Translator()
OutType = str


def type_one_tuple() -> None:
    expected = tuple[OutType]

    ti = (1,)
    assert_type(t.translate(ti), expected)
    assert_type(t.translate(ti, inplace=False), expected)
    assert_type(t.translate(ti, inplace=True), NoReturn)

    ts = ("1",)
    assert_type(t.translate(ts), expected)
    assert_type(t.translate(ts, inplace=False), expected)
    assert_type(t.translate(ts, inplace=True), NoReturn)


def type_two_tuple() -> None:
    expected = tuple[OutType, OutType]

    ti = (1, 2)
    assert_type(t.translate(ti), expected)
    assert_type(t.translate(ti, inplace=False), expected)
    assert_type(t.translate(ti, inplace=True), NoReturn)

    ts = ("1", "2")
    assert_type(t.translate(ts), expected)
    assert_type(t.translate(ts, inplace=False), expected)
    assert_type(t.translate(ts, inplace=True), NoReturn)


def type_three_tuple() -> None:
    expected = tuple[OutType, OutType, OutType]

    ti = (1, 2, 3)
    assert_type(t.translate(ti), expected)
    assert_type(t.translate(ti, inplace=False), expected)
    assert_type(t.translate(ti, inplace=True), NoReturn)

    ts = ("1", "2", "3")
    assert_type(t.translate(ts), expected)
    assert_type(t.translate(ts, inplace=False), expected)
    assert_type(t.translate(ts, inplace=True), NoReturn)
