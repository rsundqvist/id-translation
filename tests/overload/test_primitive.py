from typing import NoReturn, assert_type
from uuid import UUID

from id_translation import Translator
from id_translation.types import IdTypes

t: Translator[str, str, IdTypes] = Translator()
OutType = str


def type_int():
    i: int = 1
    assert_type(t.translate(i), OutType)
    assert_type(t.translate(i, inplace=False), OutType)
    assert_type(t.translate(i, inplace=True), NoReturn)


def type_str():
    s = "1"
    assert_type(t.translate(s), OutType)
    assert_type(t.translate(s, inplace=False), OutType)
    assert_type(t.translate(s, inplace=True), NoReturn)


def type_uuid():
    u = UUID(int=0)
    assert_type(t.translate(u), OutType)
    assert_type(t.translate(u, inplace=False), OutType)
    assert_type(t.translate(u, inplace=True), NoReturn)
