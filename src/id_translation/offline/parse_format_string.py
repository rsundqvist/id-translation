"""Utility module for parsing raw ``Format`` input strings."""

from dataclasses import dataclass as _dataclass
from string import Formatter as _Formatter
from typing import List, List as _List

OPTIONAL_BLOCK_START_DELIMITER = "["
OPTIONAL_BLOCK_END_DELIMITER = "]"

_formatter = _Formatter()
_hint = (
    f"Hint: Use double characters to escape '{OPTIONAL_BLOCK_START_DELIMITER}' and '{OPTIONAL_BLOCK_END_DELIMITER}', "
    f"e.g. '{OPTIONAL_BLOCK_START_DELIMITER * 2}' to render a single '{OPTIONAL_BLOCK_START_DELIMITER}'-character."
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


class UnusedOptionalBlockError(MalformedOptionalBlockError):
    """Errors raised when optional blocks do not use any placeholders."""

    def __init__(self, format_string: str, open_idx: int, idx: int) -> None:
        problem_locations = MalformedOptionalBlockError.get_marker_row(format_string, open_idx, idx)
        super().__init__(
            f"""Malformed optional block. No {{placeholders}} found in range {open_idx, idx}).
'{format_string}'
 {problem_locations}
{_hint}""".strip()
        )


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
    placeholders: _List[str]
    """Placeholder names in `part`, if any."""
    required: bool
    """Flag indicating whether the element may be excluded."""

    @property
    def positional_part(self) -> str:
        """Return a positional version of the `part` attribute."""
        if not self.placeholders:
            return self.part

        return self.part.format(**{p: "{}" for p in self.placeholders})

    @staticmethod
    def make(s: str, in_optional_block: bool) -> "Element":
        """Create an ``Element`` from an input string `s`.

        Args:
            s: Input data.
            in_optional_block: Flag indicating whether `s` was found inside an optional block.

        Returns:
            A new ``Element``.
        """
        parsed_block = s.replace("[[", "[").replace("]]", "]")
        placeholders = [x[1] for x in _formatter.parse(parsed_block) if x[1]]

        return Element(
            parsed_block,
            placeholders,
            not (placeholders and in_optional_block),
        )


def get_elements(fmt: str) -> List[Element]:
    """Split a format string into elements.

    Args:
        fmt: User input string.

    Returns:
        A list of parsed elements.

    Raises:
        BadDelimiterError: For unbalanced optional block delimitation characters.
        UnusedOptionalBlockError: If optional blocks are defined without placeholders.
    """
    if not fmt:
        return [Element("", [], required=True)]

    same_count = 1
    ans = []

    in_optional_block = fmt[0] == OPTIONAL_BLOCK_START_DELIMITER
    open_idx = 0 if in_optional_block else -1
    prev_idx = int(in_optional_block)

    for idx in range(int(in_optional_block), len(fmt)):
        char = fmt[idx]
        next_char = fmt[idx + 1] if idx + 1 < len(fmt) else None
        is_delimiter_char = char in (OPTIONAL_BLOCK_START_DELIMITER, OPTIONAL_BLOCK_END_DELIMITER)
        if next_char == char and is_delimiter_char:
            same_count += 1
        else:
            if same_count % 2 and is_delimiter_char:
                if char == OPTIONAL_BLOCK_START_DELIMITER:
                    if open_idx != -1:
                        raise BadDelimiterError(fmt, open_idx, idx)
                    open_idx = idx
                else:
                    if open_idx == -1:
                        raise BadDelimiterError(fmt, open_idx, idx)
                    open_idx = -1

                if prev_idx != idx:
                    element = Element.make(fmt[prev_idx:idx], in_optional_block)
                    if in_optional_block and not element.placeholders:
                        raise UnusedOptionalBlockError(fmt, prev_idx - 1, idx)
                    ans.append(element)
                in_optional_block = not in_optional_block
                prev_idx = idx + 1

            same_count = 1

    if prev_idx != len(fmt):
        ans.append(Element.make(fmt[prev_idx:], in_optional_block))

    if in_optional_block:
        raise BadDelimiterError(fmt, open_idx, -1)

    return ans
