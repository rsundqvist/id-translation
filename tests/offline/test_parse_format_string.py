import pytest as pytest

from id_translation.offline.parse_format_string import get_elements  # _is_delimiter,
from id_translation.offline.parse_format_string import BadDelimiterError, Element, UnusedOptionalBlockError


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
                Element(part="{id}", placeholders=["id"], required=True, positional_part="{:}"),
            ],
        ),
        (
            "[{optional-id}] [[literal-angle-brackets]]",
            [
                Element(part="{optional-id}", placeholders=["optional-id"], required=False, positional_part="{:}"),
                Element(
                    part=" [literal-angle-brackets]",
                    placeholders=[],
                    required=True,
                    positional_part=" [literal-angle-brackets]",
                ),
            ],
        ),
        (
            "{id} [[literal-angle-brackets]]",
            [
                Element(
                    part="{id} [literal-angle-brackets]",
                    placeholders=["id"],
                    required=True,
                    positional_part="{:} [literal-angle-brackets]",
                ),
            ],
        ),
        (
            "!{id}:[:{code}<]:{name}<",
            [
                Element(part="!{id}:", placeholders=["id"], required=True, positional_part="!{:}:"),
                Element(part=":{code}<", placeholders=["code"], required=False, positional_part=":{:}<"),
                Element(part=":{name}<", placeholders=["name"], required=True, positional_part=":{:}<"),
            ],
        ),
        (
            "{id}:{first_name}[ '{nickname}'][, age {age}].",
            [
                Element(
                    part="{id}:{first_name}",
                    placeholders=["id", "first_name"],
                    required=True,
                    positional_part="{:}:{:}",
                ),
                Element(part=" '{nickname}'", placeholders=["nickname"], required=False, positional_part=" '{:}'"),
                Element(part=", age {age}", placeholders=["age"], required=False, positional_part=", age {:}"),
                Element(part=".", placeholders=[], required=True, positional_part="."),
            ],
        ),
    ],
)
def test_get_elements(fmt, expected):
    actual = get_elements(fmt)
    assert actual == expected


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


def test_optional_block_without_placeholders():
    with pytest.raises(UnusedOptionalBlockError, match="(1, 6)"):
        get_elements(" [aaaa] ")
