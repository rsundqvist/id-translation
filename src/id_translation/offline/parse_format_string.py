"""Utility module for parsing raw ``Format`` input strings."""

import collections.abc as _abc
from dataclasses import dataclass as _dataclass
from dataclasses import field as _field
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
    placeholder_attributes: list[str | None]
    """Attribute-access/indexing suffix per :attr:`placeholders` element, in order.

    Element ``i`` is the suffix for ``placeholders[i]`` (e.g. ``"name.first"`` or ``"[0]"``), or ``None`` for
    placeholders that use neither.
    """


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
    placeholder_attributes: list[tuple[str, str]] = _field(default_factory=list)
    """A list of tuples ``[(placeholder, attribute), ..]``.

    Order matches :attr:`placeholders`, excluding placeholders without attribute access (i.e., the "values" will
    never be blank). This is essentially a ``dict`` with possible repeated keys.
    """

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

        positional_part, placeholders, attributes = cls.parse_block(fmt)
        is_optional = placeholders and in_optional_block

        return Element(
            fmt,
            placeholders,
            required=not is_optional,
            positional_part=positional_part,
            placeholder_attributes=[(p, a) for p, a in zip(placeholders, attributes, strict=True) if a],
        )

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

            >>> block, placeholders, _ = Element.parse_block("{id!s:.8}:{name!r}")
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

            >>> block, placeholders, _ = Element.parse_block(
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
        attributes = []

        formatter = _Formatter()

        for literal_text, field_name, format_spec, conversion in formatter.parse(block):
            if literal_text:
                parts.append(literal_text.replace("{", "{{").replace("}", "}}"))

            if field_name == "":
                msg = f"Bad {block=}; anonymous fields are not permitted."
                msg += "\n- Hint: Replace '{}' with '{field_name}' to give this field a name"
                msg += "\n- Hint: Replace '{}' with '{{}}' to render literal curly braces"
                raise ValueError(msg)

            if field_name:
                placeholder, attribute = cls._parse_field_name(field_name)
                if placeholder not in defaults:
                    attributes.append(attribute or None)

                formatting_parts = _get_formatting_parts(attribute, conversion=conversion, format_spec=format_spec)

                if placeholder in defaults:
                    formatting = "".join(["{", *formatting_parts, "}"])
                    value = defaults[placeholder]
                    parts.append(formatting.format(value))
                else:
                    parts.append("{")

                    placeholders.append(placeholder)
                    if keep_placeholder_names:
                        parts.append(placeholder)

                    parts.extend(formatting_parts)
                    parts.append("}")

        return ParseBlockResult("".join(parts), placeholders=placeholders, placeholder_attributes=attributes)

    @classmethod
    def _parse_field_name(cls, field_name: str) -> tuple[str, str]:
        # Determine root placeholder and the attribute-formatting suffix.
        dot_idx = field_name.find(".")
        br_idx = field_name.find("[")

        if dot_idx != -1 and (br_idx == -1 or dot_idx < br_idx):
            # dot comes before any bracket -> 'obj.attr...'
            attr = field_name[dot_idx + 1 :].strip()
            return field_name[:dot_idx], attr

        if br_idx != -1:
            # bracket comes first -> 'obj[index]...'
            attr = field_name[br_idx:].strip()
            return field_name[:br_idx], attr

        # No indexing or attribute access.
        return field_name, ""


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
    attribute: str | None,
    *,
    conversion: str | None,
    format_spec: str | None,
) -> _abc.Iterable[str]:
    if attribute:
        # If the attribute starts with '[' it already contains indexing and possibly
        # further chained attribute access (e.g. '[4].bool'). Yield it as-is.
        if attribute.startswith("["):
            yield attribute
        else:
            # Otherwise, render as attribute access; keep any embedded indexing intact
            # (e.g. 'mapping[int].child' becomes '.mapping[int].child').
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

    in_field = False
    for idx in range(int(in_optional_block), len(fmt)):
        char = fmt[idx]
        next_char = fmt[idx + 1] if idx + 1 < len(fmt) else None
        prev_char = fmt[idx - 1] if idx - 1 >= 0 else None

        # Track whether we are inside a format field because '[' and ']' inside
        # a field (e.g. '{obj[0]}') must not be treated as optional-block delimiters.
        if char == "{" and next_char != "{":
            in_field = True
        elif char == "}" and prev_char != "}":
            in_field = False

        is_delimiter_char = (char in (_START, _END)) and not in_field

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
