from datetime import datetime
from uuid import UUID

import pytest as pytest

from id_translation.offline import Format


@pytest.fixture(scope="module")
def fmt():
    yield Format("{id}:[{code}:]{name}")


@pytest.mark.parametrize(
    "placeholders, expected",
    [
        (("id", "code", "name"), "{id}:{code}:{name}"),
        (("id", "name"), "{id}:{name}"),
    ],
)
def test_for_placeholders(fmt, placeholders, expected):
    assert fmt.fstring(placeholders) == expected


@pytest.mark.parametrize(
    "translations, expected",
    [
        ({"id": 1, "code": "SE", "name": "Sweden"}, "1:SE:Sweden"),
        ({"id": 1, "name": "Sweden"}, "1:Sweden"),
    ],
)
def test_format(fmt, translations, expected):
    assert fmt.fstring(translations).format(**translations) == expected


def test_missing_required(fmt):
    with pytest.raises(KeyError):
        fmt.fstring(("does", "not", "exist"))


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"id": "my-id"}, "{my-id} is required!"),
        ({"id": "my-id", "optional": "my-optional"}, "{my-id} is required, 'my-optional' is [optional]!"),
    ],
)
def test_nested(kwargs, expected):
    fmt = Format("{{{id}}} is required[, '{optional}' is [[optional]]]!")
    fstring = fmt.fstring(kwargs)
    assert fstring.format(**kwargs) == expected


def test_multiple_optional_placeholders():
    fmt = Format("{required}[ opt0={opt0}, opt1={opt1}]")

    assert fmt.fstring(["required"]) == "{required}"
    assert fmt.fstring(["required", "opt0"]) == "{required}"
    assert fmt.fstring(["required", "opt1"]) == "{required}"
    assert fmt.fstring(["required", "opt0", "opt1"]) == "{required} opt0={opt0}, opt1={opt1}"


@pytest.mark.parametrize(
    "fmt, expected",
    [
        ("{id}:{name}", "1999:Sofia"),  # Baseline
        ("{id!r}:{name!r}", "1999:'Sofia'"),
        ("{id:.2f}:{name:.2}", "1999.00:So"),
        ("{id:*^11.2f}:{name!r:.2}", "**1999.00**:'S"),
        ("{id.imag:*^11.2f}:{name}", "***0.00****:Sofia"),
    ],
)
def test_formatting(fmt, expected):
    kwargs = {"id": 1999, "name": "Sofia"}
    assert fmt.format(**kwargs) == expected, "bad test case"

    fstring = Format(fmt).fstring
    positional_true = fstring(positional=True).format(*kwargs.values())
    positional_false = fstring(positional=False).format(**kwargs)

    assert positional_true == expected
    assert positional_false == expected


class TestPartial:
    @pytest.mark.parametrize("id_part", ["{id}", "{id!r}", "{id!s:8.2}", "{id!r:^12}"])
    def test_string(self, id_part):
        self.run(id_part, kind=str)

    @pytest.mark.parametrize("id_part", ["{id}", "{id!r}", "{id!s:8.2}", "{id:+_d}", "{id:_d}"])
    def test_int(self, id_part):
        self.run(id_part, kind=int)

    @pytest.mark.parametrize("id_part", ["{id}", "{id!r}", "{id:%A, %d %B %Y}", "{id.date.__qualname__!r}"])
    def test_datetime(self, id_part):
        self.run(id_part, kind=datetime)

    @pytest.mark.parametrize("id_part", ["{id}", "{id!r}", "{id.int:_d}"])
    def test_uuid(self, id_part):
        self.run(id_part, kind=UUID)

    @staticmethod
    def run(id_part, kind):
        defaults = {
            "int": 1999,
            "str": "string!",
            "datetime": datetime.fromisoformat("2019-05-11T20:30:00"),
            "uuid": UUID("00000000-0000-0000-0000-00000134152f"),
        }
        fixed = "<int={int:_d} | str={str!r} | datetime={datetime:%A, %d %B %Y} | uuid={uuid.int!r:>8.4}>"

        id_value = defaults[kind.__name__.lower()]
        expected = id_part.format(id=id_value)

        partial = Format(id_part + ": " + fixed).partial(defaults)
        actual, _, fixed_part = partial.fstring().format(id=id_value).partition(": ")

        assert fixed_part == fixed.format_map(defaults)
        assert actual == expected

    @pytest.mark.parametrize("optional", [False, True])
    def test_optional(self, optional):
        kwargs = {"required": "<Required>"}
        if optional:
            kwargs["optional"] = "<Optional>"

        expected = Format(
            "required: {required}"
            " | [1/1, <Provided optional>]"
            " | [1/2: <Provided optional> {optional}]"
            " | [2/3: <Provided optional> {optional} <Provided optional>]"
        )

        actual = Format(
            "required: {required}"
            " | [1/1, {optional_provided}]"
            " | [1/2: {optional_provided} {optional}]"
            " | [2/3: {optional_provided} {optional} {optional_provided}]"
        ).partial({"optional_provided": "<Provided optional>"})

        assert actual.fstring(kwargs).format(**kwargs) == expected.fstring(kwargs).format(**kwargs)
