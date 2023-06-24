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
