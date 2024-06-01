from typing import NoReturn, assert_type
from uuid import UUID

from id_translation import Translator
from id_translation.types import IdTypes

t: Translator[str, str, IdTypes] = Translator()
OutType = str


def type_int():
    i: int = 1
    assert_type(t.translate(i), OutType)
    assert_type(t.translate(i, copy=True), OutType)
    assert_type(t.translate(i, copy=False), NoReturn)


def type_str():
    s = "1"
    assert_type(t.translate(s), OutType)
    assert_type(t.translate(s, copy=True), OutType)
    assert_type(t.translate(s, copy=False), NoReturn)


def type_uuid():
    u = UUID(int=0)
    assert_type(t.translate(u), OutType)
    assert_type(t.translate(u, copy=True), OutType)
    assert_type(t.translate(u, copy=False), NoReturn)
