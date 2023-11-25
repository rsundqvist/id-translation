"""Utility module for parsing raw ``Format`` input strings."""

import typing as _t
from dataclasses import dataclass as _dataclass
from string import Formatter as _Formatter

OPTIONAL_BLOCK_START_DELIMITER = "["
_START = OPTIONAL_BLOCK_START_DELIMITER
OPTIONAL_BLOCK_END_DELIMITER = "]"
_END = OPTIONAL_BLOCK_END_DELIMITER

_formatter = _Formatter()
_hint = (
    f"Hint: Use double characters to escape '{_START}' and '{_END}', "
    f"e.g. '{_START * 2}' to render a single '{_START}'-character."
)


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
            info = (
                "there is no block to close"
                if open_idx == -1
                else f"nested optional blocks are not supported (opened at {open_idx})"
            )

            super().__init__(
                f"""Malformed optional block. Got '{format_string[idx]}' at i={idx}, but {info}.
    '{format_string}'
     {problem_locations}
{_hint}""".strip()
            )


@_dataclass(frozen=True)
class Element:
    """Information about a single block in a ``Format`` specification."""

    part: str
    """String literal."""
    placeholders: _t.List[str]
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
        # block = block.replace("{{", "{").replace("}}", "}")
        parts, placeholders = cls.parse_block(fmt)

        return Element(fmt, placeholders, not (placeholders and in_optional_block), "".join(parts))

    @classmethod
    def parse_block(cls, block: str, defaults: _t.Mapping[str, _t.Any] = None) -> _t.Tuple[_t.List[str], _t.List[str]]:
        """Parse an entire block with optional defaults for placeholders found.

        Using `defaults`:
            Keys in `defaults` will replace placeholders in the block. That is, the returned placeholders are guaranteed
            not to contain any keys in the `defaults`. Passing defaults will retain placeholder names in the returned
            `parts`.

        If `defaults` are not given, placeholder values are strip from returned `parts`.

        Args:
            block: A block to parse.
            defaults: A dict ``{placeholder: value}``.

        Returns:
            A tuple of two lists ``([positional_parts...], [placeholders...])``.
        """
        if defaults is None:
            defaults = {}
            positional = True
        else:
            positional = False

        parts = []
        placeholders = []

        # Optional block backtracking
        replaced_parts_index = []
        placeholders_index = []

        for literal_text, field_name, format_spec, conversion in _formatter.parse(block):
            parts.append(literal_text.replace("{", "{{").replace("}", "}}"))
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
                    if not positional:
                        placeholders_index.append(len(parts))
                        parts.append(placeholder)

                    parts.extend(formatting_parts)
                    parts.append("}")

        return parts, placeholders


def _get_delimiter_index(part: str, *, start: bool) -> _t.Optional[int]:
    def _exec(func: _t.Callable[[str], int], sign: str) -> _t.Optional[int]:
        try:
            return func(sign)
        except ValueError:
            return None

    if start:
        return _exec(part.index, _START)
    else:
        return _exec(part.rindex, _END)


def _get_formatting_parts(
    *, attribute: _t.Optional[str], conversion: _t.Optional[str], format_spec: _t.Optional[str]
) -> _t.Iterable[str]:
    if attribute:
        yield "."
        yield attribute
    if conversion is not None:
        yield "!"
        yield conversion
    if format_spec is not None and format_spec != "":
        yield ":"
        yield format_spec


def get_elements(fmt: str) -> _t.List[Element]:
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
