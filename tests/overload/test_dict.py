from typing import Any, Dict, List, Set, Tuple
from uuid import UUID

from typing_extensions import assert_type

from id_translation import Translator

t: Translator[int, str, Any] = Translator()
OutType = str


def type_dict_primitive() -> None:
    expected = Dict[int, OutType]

    di = {1: 1}
    assert_type(t.translate(di), expected)
    assert_type(t.translate(di, inplace=False), expected)
    assert_type(t.translate(di, inplace=True), None)

    ds = {1: "1"}
    assert_type(t.translate(ds), expected)
    assert_type(t.translate(ds, inplace=False), expected)
    assert_type(t.translate(ds, inplace=True), None)

    du = {1: UUID(int=0)}
    assert_type(t.translate(du), expected)
    assert_type(t.translate(du, inplace=False), expected)
    assert_type(t.translate(du, inplace=True), None)


def type_dict_set() -> None:
    expected = Dict[int, Set[OutType]]

    dsi = {1: {1}}
    assert_type(t.translate(dsi), expected)
    assert_type(t.translate(dsi, inplace=False), expected)
    assert_type(t.translate(dsi, inplace=True), None)

    dss = {1: {"1"}}
    assert_type(t.translate(dss), expected)
    assert_type(t.translate(dss, inplace=False), expected)
    assert_type(t.translate(dss, inplace=True), None)


def type_dict_list() -> None:
    expected = Dict[int, List[OutType]]

    dli = {1: [1]}
    assert_type(t.translate(dli), expected)
    assert_type(t.translate(dli, inplace=False), expected)
    assert_type(t.translate(dli, inplace=True), None)

    dss = {1: ["1"]}
    assert_type(t.translate(dss), expected)
    assert_type(t.translate(dss, inplace=False), expected)
    assert_type(t.translate(dss, inplace=True), None)


def type_dict_one_tuple() -> None:
    expected = Dict[int, Tuple[str]]

    dti = {1: (1,)}  # Anonymous instance is cast to vararg-tuple by mypy
    assert_type(t.translate(dti), expected)
    assert_type(t.translate(dti, inplace=False), expected)
    assert_type(t.translate(dti, inplace=True), None)

    dts = {1: ("1",)}  # Anonymous instance is cast to vararg-tuple by mypy
    assert_type(t.translate(dts), expected)
    assert_type(t.translate(dts, inplace=False), expected)
    assert_type(t.translate(dts, inplace=True), None)


def type_dict_two_tuple() -> None:
    expected = Dict[int, Tuple[str, str]]

    di = {1: (1, 2)}  # Anonymous instance is cast to vararg-tuple by mypy
    assert_type(t.translate(di), expected)
    assert_type(t.translate(di, inplace=False), expected)
    assert_type(t.translate(di, inplace=True), None)

    ds = {1: ("1", "2")}  # Anonymous instance is cast to vararg-tuple by mypy
    assert_type(t.translate(ds), expected)
    assert_type(t.translate(ds, inplace=False), expected)
    assert_type(t.translate(ds, inplace=True), None)


def type_dict_three_tuple() -> None:
    expected = Dict[int, Tuple[str, str, str]]

    dti = {1: (1, 2, 3)}  # Anonymous instance is cast to vararg-tuple by mypy
    assert_type(t.translate(dti), expected)
    assert_type(t.translate(dti, inplace=False), expected)
    assert_type(t.translate(dti, inplace=True), None)

    dts = {1: ("1", "2", "3")}  # Anonymous instance is cast to vararg-tuple by mypy
    assert_type(t.translate(dts), expected)
    assert_type(t.translate(dts, inplace=False), expected)
    assert_type(t.translate(dts, inplace=True), None)


def type_dict_var_tuple() -> None:
    expected = Dict[int, Tuple[str, ...]]

    dti = {1: tuple(range(1))}
    assert_type(t.translate(dti), expected)
    assert_type(t.translate(dti, inplace=False), expected)
    assert_type(t.translate(dti, inplace=True), None)

    dts = {1: tuple("1")}
    assert_type(t.translate(dts), expected)
    assert_type(t.translate(dts, inplace=False), expected)
    assert_type(t.translate(dts, inplace=True), None)
