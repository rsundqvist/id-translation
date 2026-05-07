"""Test indexing in Format."""

import pytest

from id_translation import Translator


@pytest.mark.parametrize(
    "fmt, expected",
    [
        ("{obj}", "Dummy()"),
        ("{obj.int}", "123"),
        ("{obj.float}", "3.21"),
        ("{obj.bool}", "True"),
        ("{obj.str}", "string"),
        ("{obj.Dummy}", "Dummy()"),
    ],
)
def test_basic(fmt, expected, translator):
    _run(expected, fmt, translator)


class TestDirectIndex:
    @pytest.mark.parametrize(
        "fmt, expected",
        [
            ("{obj[int]}", "123"),
            ("{obj[float]}", "3.21"),
            ("{obj[bool]}", "True"),
            ("{obj[str]}", "string"),
            ("{obj[Dummy]}", "Dummy()"),
        ],
    )
    def test_str(self, fmt, expected, translator):
        _run(expected, fmt, translator)

    @pytest.mark.parametrize(
        "fmt, expected",
        [
            ("{obj[0]}", "123"),
            ("{obj[1]}", "3.21"),
            ("{obj[2]}", "True"),
            ("{obj[3]}", "string"),
            ("{obj[4]}", "Dummy()"),
        ],
    )
    def test_int(self, fmt, expected, translator):
        _run(expected, fmt, translator)


class TestAttributeIndex:
    @pytest.mark.parametrize(
        "fmt, expected",
        [
            ("{obj.mapping[int]}", "123"),
            ("{obj.mapping[float]}", "3.21"),
            ("{obj.mapping[bool]}", "True"),
            ("{obj.mapping[str]}", "string"),
        ],
    )
    def test_str(self, fmt, expected, translator):
        _run(expected, fmt, translator)

    @pytest.mark.parametrize(
        "fmt, expected",
        [
            ("{obj.sequence[0]}", "123"),
            ("{obj.sequence[1]}", "3.21"),
            ("{obj.sequence[2]}", "True"),
            ("{obj.sequence[3]}", "string"),
        ],
    )
    def test_int(self, fmt, expected, translator):
        _run(expected, fmt, translator)


def _run(expected, fmt, translator):
    actual = fmt.format(obj=Dummy())
    assert actual == expected, "built-in string failed"

    actual = translator.translate(0, names="source")
    assert actual == expected, "Format failed"


@pytest.fixture
def translator(fmt):
    data = {"source": {"id": [0], "obj": [Dummy()]}}
    return Translator(data, fmt=fmt)


class Dummy:
    def __init__(self):
        self.sequence = [123, 3.21, True, "string", self]
        self.mapping = {type(v).__name__: v for v in self.sequence}
        self.this = self

    def __getattr__(self, name):
        return self.mapping[name]

    def __repr__(self):
        return type(self).__name__ + "()"

    def __getitem__(self, key):
        if isinstance(key, str):
            return self.mapping[key]
        else:
            return self.sequence[key]
