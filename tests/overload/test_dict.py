from typing import Any, assert_type
from uuid import UUID

from id_translation import Translator

t: Translator[int, str, Any] = Translator()
OutType = str


def type_dict_primitive() -> None:
    expected = dict[int, OutType]

    di = {1: 1}
    assert_type(t.translate(di), expected)
    assert_type(t.translate(di, copy=True), expected)
    assert_type(t.translate(di, copy=False), None)

    ds = {1: "1"}
    assert_type(t.translate(ds), expected)
    assert_type(t.translate(ds, copy=True), expected)
    assert_type(t.translate(ds, copy=False), None)

    du = {1: UUID(int=0)}
    assert_type(t.translate(du), expected)
    assert_type(t.translate(du, copy=True), expected)
    assert_type(t.translate(du, copy=False), None)


def type_dict_set() -> None:
    expected = dict[int, set[OutType]]

    dsi = {1: {1}}
    assert_type(t.translate(dsi), expected)
    assert_type(t.translate(dsi, copy=True), expected)
    assert_type(t.translate(dsi, copy=False), None)

    dss = {1: {"1"}}
    assert_type(t.translate(dss), expected)
    assert_type(t.translate(dss, copy=True), expected)
    assert_type(t.translate(dss, copy=False), None)


def type_dict_list() -> None:
    expected = dict[int, list[OutType]]

    dli = {1: [1]}
    assert_type(t.translate(dli), expected)
    assert_type(t.translate(dli, copy=True), expected)
    assert_type(t.translate(dli, copy=False), None)

    dss = {1: ["1"]}
    assert_type(t.translate(dss), expected)
    assert_type(t.translate(dss, copy=True), expected)
    assert_type(t.translate(dss, copy=False), None)


def type_dict_one_tuple() -> None:
    expected = dict[int, tuple[str]]

    dti = {1: (1,)}  # Anonymous instance is cast to vararg-tuple by mypy
    assert_type(t.translate(dti), expected)
    assert_type(t.translate(dti, copy=True), expected)
    assert_type(t.translate(dti, copy=False), None)

    dts = {1: ("1",)}  # Anonymous instance is cast to vararg-tuple by mypy
    assert_type(t.translate(dts), expected)
    assert_type(t.translate(dts, copy=True), expected)
    assert_type(t.translate(dts, copy=False), None)


def type_dict_two_tuple() -> None:
    expected = dict[int, tuple[str, str]]

    di = {1: (1, 2)}  # Anonymous instance is cast to vararg-tuple by mypy
    assert_type(t.translate(di), expected)
    assert_type(t.translate(di, copy=True), expected)
    assert_type(t.translate(di, copy=False), None)

    ds = {1: ("1", "2")}  # Anonymous instance is cast to vararg-tuple by mypy
    assert_type(t.translate(ds), expected)
    assert_type(t.translate(ds, copy=True), expected)
    assert_type(t.translate(ds, copy=False), None)


def type_dict_three_tuple() -> None:
    expected = dict[int, tuple[str, str, str]]

    dti = {1: (1, 2, 3)}  # Anonymous instance is cast to vararg-tuple by mypy
    assert_type(t.translate(dti), expected)
    assert_type(t.translate(dti, copy=True), expected)
    assert_type(t.translate(dti, copy=False), None)

    dts = {1: ("1", "2", "3")}  # Anonymous instance is cast to vararg-tuple by mypy
    assert_type(t.translate(dts), expected)
    assert_type(t.translate(dts, copy=True), expected)
    assert_type(t.translate(dts, copy=False), None)


def type_dict_var_tuple() -> None:
    expected = dict[int, tuple[str, ...]]

    dti = {1: tuple(range(1))}
    assert_type(t.translate(dti), expected)
    assert_type(t.translate(dti, copy=True), expected)
    assert_type(t.translate(dti, copy=False), None)

    dts = {1: tuple("1")}
    assert_type(t.translate(dts), expected)
    assert_type(t.translate(dts, copy=True), expected)
    assert_type(t.translate(dts, copy=False), None)
