"""Utility module for parsing raw ``Format`` input strings."""

import collections.abc as _abc
from dataclasses import dataclass as _dataclass
from string import Formatter as _Formatter
from typing import Any as _Any
from typing import NamedTuple as _NamedTuple

OPTIONAL_BLOCK_START_DELIMITER = "["
_START = OPTIONAL_BLOCK_START_DELIMITER
OPTIONAL_BLOCK_END_DELIMITER = "]"
_END = OPTIONAL_BLOCK_END_DELIMITER


class ParseBlockResult(_NamedTuple):
    """Output type of :meth:`.Element.parse_block`."""

    parsed_block: str
    """Processed parts of the block."""
    placeholders: list[str]
    """Names of the :attr:`.Format.placeholders` in `parsed_block`, in the order in which they appear."""


class MalformedOptionalBlockError(ValueError):
    """Error raised for improper optional blocks."""

    @staticmethod
    def get_marker_row(format_string: str, open_idx: int = -1, idx: int = -1) -> str:
        """Get a string of length equal to `format_string` which marks problem locations."""
        markers = [" "] * len(format_string)

        if idx != -1:
            markers[idx] = "^"
        if open_idx != -1:
            markers[open_idx] = "^"
        return "".join(markers)


class BadDelimiterError(MalformedOptionalBlockError):
    """Errors raised due to mismatched delimiters."""

    def __init__(self, format_string: str, open_idx: int, idx: int) -> None:
        problem_locations = MalformedOptionalBlockError.get_marker_row(format_string, open_idx, idx)

        if idx == -1:
            super().__init__(
                f"""Malformed optional block. Optional block opened at i={open_idx} was never closed.
'{format_string}'
 {problem_locations}""".strip()
            )
        else:
            hint = (
                f"Hint: Use double characters to escape '{_START}' and '{_END}', "
                f"e.g. '{_START * 2}' to render a single '{_START}'-character."
            )
            info = (
                "there is no block to close"
                if open_idx == -1
                else f"nested optional blocks are not supported (opened at {open_idx})"
            )

            super().__init__(
                f"""Malformed optional block. Got '{format_string[idx]}' at i={idx}, but {info}.
    '{format_string}'
     {problem_locations}
{hint}""".strip()
            )


@_dataclass(frozen=True)
class Element:
    """Information about a single block in a ``Format`` specification."""

    part: str
    """String literal."""
    placeholders: list[str]
    """Placeholder names in `part`, if any."""
    required: bool
    """Flag indicating whether the element may be excluded."""
    positional_part: str
    """Return a positional version of the `part` attribute."""

    @classmethod
    def make(cls, fmt: str, in_optional_block: bool) -> "Element":
        """Create an ``Element`` from an input string `s`.

        Args:
            fmt: Input data.
            in_optional_block: Flag indicating whether `s` was found inside an optional block.

        Returns:
            A new ``Element``.
        """
        block = fmt
        fmt = block.replace("[[", "[").replace("]]", "]")

        positional_part, placeholders = cls.parse_block(fmt)
        is_optional = placeholders and in_optional_block

        return Element(fmt, placeholders, required=not is_optional, positional_part=positional_part)

    @classmethod
    def parse_block(cls, block: str, defaults: _abc.Mapping[str, _Any] | None = None) -> ParseBlockResult:
        """Parse an entire block with optional defaults for placeholders found.

        .. hint::

           With `defaults`, the value of the :attr:`ParseBlockResult.parsed_block` is more or less what you'd expect if
           the built-in :py:meth:`str.format_map`-method allowed missing keys.

        Anonymous fields are not permitted.

        ..
           >>> from uuid import UUID

        Output with ``defaults == None``:
            When `defaults` are ``None``, placeholder names are stripped from the
            :attr:`~.ParseBlockResult.parsed_block`.

            >>> block, placeholders = Element.parse_block("{id!s:.8}:{name!r}")
            >>> print(f"{block=} has {placeholders=}")
            block='{!s:.8}:{!r}' has placeholders=['id', 'name']

            Field names in `block` are returned as :attr:`.ParseBlockResult.placeholders`, in the order in which they
            appeared in the input `block`. The field names of :attr:`~.ParseBlockResult.parsed_block` will be
            anonymous.

            >>> block.format(UUID(int=10**38), "Morran Borran")
            "4b3b4ca8:'Morran Borran'"

        Output with ``defaults != None``:
            When `defaults` are given, all placeholders in the `block` which are present in the `defaults` are replaced
            with ``defaults[field_name]`` in the :attr:`~.ParseBlockResult.parsed_block`.

            >>> block, placeholders = Element.parse_block(
            ...     "{id!s:.8}:{name!r}",
            ...     defaults={"name": "Morran Borran"},
            ... )
            >>> print(f"{block=} has {placeholders=}")
            block="{id!s:.8}:'Morran Borran'" has placeholders=['id']

            Field names without defaults will be present both in :attr:`~.ParseBlockResult.placeholders`, and as named
            fields in the :attr:`~.ParseBlockResult.parsed_block`.

            >>> block.format(id=UUID(int=10**38))
            "4b3b4ca8:'Morran Borran'"

        Args:
            block: A block to parse.
            defaults: A dict ``{placeholder: value}``.

        Returns:
            A :class:`.ParseBlockResult` tuple.

        Raises:
            ValueError: If `block` contains anonymous fields.
        """
        if defaults is None:
            defaults = {}
            keep_placeholder_names = False
        else:
            keep_placeholder_names = True

        parts = []
        placeholders = []

        # Optional block backtracking
        replaced_parts_index = []
        placeholders_index = []

        formatter = _Formatter()

        for literal_text, field_name, format_spec, conversion in formatter.parse(block):
            parts.append(literal_text.replace("{", "{{").replace("}", "}}"))

            if field_name == "":
                msg = f"Bad {block=}; anonymous fields are not permitted."
                msg += "\n- Hint: Replace '{}' with '{field_name}' to give this field a name"
                msg += "\n- Hint: Replace '{}' with '{{}}' to render literal curly braces"
                raise ValueError(msg)

            if field_name:
                placeholder, _, attribute = field_name.partition(".")
                formatting_parts = _get_formatting_parts(
                    attribute=attribute, conversion=conversion, format_spec=format_spec
                )

                if placeholder in defaults:
                    replaced_parts_index.append(len(parts))
                    formatting = "".join(["{", *formatting_parts, "}"])
                    value = defaults[placeholder]
                    parts.append(formatting.format(value))
                else:
                    parts.append("{")

                    placeholders.append(placeholder)
                    if keep_placeholder_names:
                        placeholders_index.append(len(parts))
                        parts.append(placeholder)

                    parts.extend(formatting_parts)
                    parts.append("}")

        return ParseBlockResult("".join(parts), placeholders=placeholders)


def _get_delimiter_index(part: str, *, start: bool) -> int | None:
    def _exec(func: _abc.Callable[[str], int], sign: str) -> int | None:
        try:
            return func(sign)
        except ValueError:
            return None

    if start:
        return _exec(part.index, _START)
    else:
        return _exec(part.rindex, _END)


def _get_formatting_parts(
    *,
    attribute: str | None,
    conversion: str | None,
    format_spec: str | None,
) -> _abc.Iterable[str]:
    if attribute:
        yield "."
        yield attribute
    if conversion is not None:
        yield "!"
        yield conversion
    if format_spec is not None and format_spec != "":
        yield ":"
        yield format_spec


def get_elements(fmt: str) -> list[Element]:  # noqa: PLR0912
    """Split a format string into elements.

    Args:
        fmt: User input string.

    Returns:
        A list of parsed elements.

    Raises:
        BadDelimiterError: For unbalanced optional block delimitation characters.
    """
    if not fmt:
        return [Element("", [], required=True, positional_part="")]

    same_count = 1
    ans = []

    in_optional_block = fmt[0] == _START
    open_idx = 0 if in_optional_block else -1
    prev_idx = int(in_optional_block)

    for idx in range(int(in_optional_block), len(fmt)):
        char = fmt[idx]
        next_char = fmt[idx + 1] if idx + 1 < len(fmt) else None
        is_delimiter_char = char in (_START, _END)
        if next_char == char and is_delimiter_char:
            same_count += 1
        else:
            if same_count % 2 and is_delimiter_char:
                if char == _START:
                    if open_idx != -1:
                        raise BadDelimiterError(fmt, open_idx, idx)
                    open_idx = idx
                else:
                    if open_idx == -1:
                        raise BadDelimiterError(fmt, open_idx, idx)
                    open_idx = -1

                if prev_idx != idx:
                    part = fmt[prev_idx:idx]
                    element = Element.make(part, in_optional_block)
                    if in_optional_block and not element.placeholders:
                        # Convert to required
                        element = Element.make(_START + part + _END, True)
                        assert element.required is True  # noqa: S101
                        assert len(element.placeholders) == 0  # noqa: S101
                        assert element.part == element.positional_part  # noqa: S101
                    ans.append(element)
                in_optional_block = not in_optional_block
                prev_idx = idx + 1

            same_count = 1

    if prev_idx != len(fmt):
        ans.append(Element.make(fmt[prev_idx:], in_optional_block))

    if in_optional_block:
        raise BadDelimiterError(fmt, open_idx, -1)

    return ans
