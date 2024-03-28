import pytest
from id_translation.offline.parse_format_string import BadDelimiterError, Element, get_elements


@pytest.mark.parametrize(
    "fmt, expected",
    [
        (
            "static",
            [
                Element(part="static", placeholders=[], required=True, positional_part="static"),
            ],
        ),
        (
            "{id}",
            [
                Element(part="{id}", placeholders=["id"], required=True, positional_part="{}"),
            ],
        ),
        (
            "{{id}}",
            [
                Element(part="{{id}}", placeholders=[], required=True, positional_part="{{id}}"),
            ],
        ),
        (
            "{{id}}, {id}",
            [
                Element(part="{{id}}, {id}", placeholders=["id"], required=True, positional_part="{{id}}, {}"),
            ],
        ),
        (
            "[{optional-id}] [literal-angle-brackets]",
            [
                Element(part="{optional-id}", placeholders=["optional-id"], required=False, positional_part="{}"),
                Element(part=" ", placeholders=[], required=True, positional_part=" "),
                Element(
                    part="[literal-angle-brackets]",
                    placeholders=[],
                    required=True,
                    positional_part="[literal-angle-brackets]",
                ),
            ],
        ),
        (
            "{id} [literal-angle-brackets]",
            [
                Element(
                    part="{id} ",
                    placeholders=["id"],
                    required=True,
                    positional_part="{} ",
                ),
                Element(
                    part="[literal-angle-brackets]",
                    placeholders=[],
                    required=True,
                    positional_part="[literal-angle-brackets]",
                ),
            ],
        ),
        (
            "!{id}:[:{code}<]:{name}<",
            [
                Element(part="!{id}:", placeholders=["id"], required=True, positional_part="!{}:"),
                Element(part=":{code}<", placeholders=["code"], required=False, positional_part=":{}<"),
                Element(part=":{name}<", placeholders=["name"], required=True, positional_part=":{}<"),
            ],
        ),
        (
            "{id}:{first_name}[ '{nickname}'][, age {age}].",
            [
                Element(
                    part="{id}:{first_name}",
                    placeholders=["id", "first_name"],
                    required=True,
                    positional_part="{}:{}",
                ),
                Element(part=" '{nickname}'", placeholders=["nickname"], required=False, positional_part=" '{}'"),
                Element(part=", age {age}", placeholders=["age"], required=False, positional_part=", age {}"),
                Element(part=".", placeholders=[], required=True, positional_part="."),
            ],
        ),
        (
            " [literal-angle-brackets] ",
            [
                Element(
                    part=" ",
                    placeholders=[],
                    required=True,
                    positional_part=" ",
                ),
                Element(
                    part="[literal-angle-brackets]",
                    placeholders=[],
                    required=True,
                    positional_part="[literal-angle-brackets]",
                ),
                Element(
                    part=" ",
                    placeholders=[],
                    required=True,
                    positional_part=" ",
                ),
            ],
        ),
        (
            " [[{required}]], [literal-angle-brackets] ",
            [
                Element(
                    part=" [{required}], ",
                    placeholders=["required"],
                    required=True,
                    positional_part=" [{}], ",
                ),
                Element(
                    part="[literal-angle-brackets]",
                    placeholders=[],
                    required=True,
                    positional_part="[literal-angle-brackets]",
                ),
                Element(
                    part=" ",
                    placeholders=[],
                    required=True,
                    positional_part=" ",
                ),
            ],
        ),
        (
            " [[{required}]], [{optional-1} [[{optional-2}]] {{just-some-curlies}}] ",
            [
                Element(
                    part=" [{required}], ",
                    placeholders=["required"],
                    required=True,
                    positional_part=" [{}], ",
                ),
                Element(
                    part="{optional-1} [{optional-2}] {{just-some-curlies}}",
                    placeholders=["optional-1", "optional-2"],
                    required=False,
                    positional_part="{} [{}] {{just-some-curlies}}",
                ),
                Element(
                    part=" ",
                    placeholders=[],
                    required=True,
                    positional_part=" ",
                ),
            ],
        ),
    ],
)
def test_get_elements(fmt, expected):
    actual = get_elements(fmt)
    if actual == expected:
        return

    for i, (a, e) in enumerate(zip(actual, expected)):
        assert a.placeholders == e.placeholders, i
        assert a.required == e.required, i

    assert "".join(a.part for a in actual) == "".join(e.part for e in expected)
    assert "".join(a.positional_part for a in actual) == "".join(e.positional_part for e in expected)

    for i, (a, e) in enumerate(zip(actual, expected)):
        assert a.placeholders == e.placeholders, i
        assert a.required == e.required, i

    assert len(actual) == len(expected)


@pytest.mark.parametrize(
    "fmt, i, msg",
    [
        ("]", 0, "no block to close"),
        ("[", 0, "never closed"),
        ("  [  ", 2, "never closed"),
        ("[{a}] ]", 6, "no block to close"),
        ("[ [", 2, "nested"),
    ],
)
def test_improper_brackets(fmt, i, msg):
    with pytest.raises(BadDelimiterError, match=f"{i=}.*{msg}"):
        get_elements(fmt)


def test_positional_fmt():
    with pytest.raises(ValueError, match="anonymous fields are not permitted"):
        get_elements("{}:{}")
