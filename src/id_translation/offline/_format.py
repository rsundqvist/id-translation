from typing import Any, Iterable, List, Mapping

from rics.misc import tname

from . import parse_format_string
from .types import FormatType, PlaceholdersTuple


class Format:
    r"""Format specification for translations strings.

    Translation formats are similar to regular f-strings, with two important exceptions:

    1. Positional placeholders (``'{}'``) may not be used; correct form is ``'{placeholder-name}'``.
    2. Placeholders surrounded by ``'[]'`` denote an optional element. Optional elements are rendered...

       * Only if `all` of its placeholders are defined.
       * Without delimiting brackets.
       * As literal text (with brackets) if there is no placeholder in the block.

    .. hint::

       Double the wanted bracket character to render as a literal, analogous to ``'{{'`` and ``'}}'``
       in plain Python f-strings. See the example below for a demonstration.

    Args:
        fmt: A translation fstring.

    Examples:
        A format string using literal angle brackets and an optional element.

        >>> from id_translation.offline import Format
        >>> fmt = Format("{id}:[[{name}]][, nice={is_nice}]")

        The ``Format`` class when used directly only returns required placeholders by default...

        >>> fmt.fstring()
        '{id}:[{name}]'
        >>> fmt.fstring().format(id=0, name="Tarzan")
        '0:[Tarzan]'

        ...but the :attr:`placeholders` attribute can be used to retrieve all placeholders, required and optional:

        >>> fmt.placeholders
        ('id', 'name', 'is_nice')
        >>> fmt.fstring(fmt.placeholders).format(id=1, name="Morris", is_nice=True)
        '1:[Morris], nice=True'

    The :class:`.Translator` will automatically add optional placeholders, if they are present in the source.

    .. note::
       Python format specifications and conversions are preserved.

    This is especially useful for long values such as UUIDs.

    >>> from uuid import UUID
    >>> uuid = UUID("550e8400-e29b-41d4-a716-446655440000")

    Convert to string and truncate to eight characters.

    >>> Format("{id!s:.8}:{name!r}").fstring().format(id=uuid, name="Sofia")
    "550e8400:'Sofia'"

    See the official :py:ref:`formatspec` documentation for details.
    """

    def __init__(self, fmt: str) -> None:
        self._fmt = fmt
        self._elements: List[parse_format_string.Element] = parse_format_string.get_elements(fmt)

    def fstring(self, placeholders: Iterable[str] = None, *, positional: bool = False) -> str:
        """Create a format string for the given placeholders.

        Args:
            placeholders: Keys to keep. Passing ``None`` is equivalent to passing :attr:`required_placeholders`.
            positional: If ``True``, remove names to return a positional fstring.

        Returns:
            An fstring with optional elements removed unless included in `placeholders`.

        Raises:
            KeyError: If required placeholders are missing.
        """
        placeholders = placeholders or self.required_placeholders
        missing_required_placeholders = set(self.required_placeholders).difference(placeholders)
        if missing_required_placeholders:
            raise KeyError(f"Required key(s) {missing_required_placeholders} missing from {placeholders=}.")

        return self._make_fstring(placeholders, positional=positional)

    def _make_fstring(self, placeholders: Iterable[str], positional: bool) -> str:
        def predicate(e: parse_format_string.Element) -> bool:
            return e.required or set(placeholders).issuperset(e.placeholders)

        return "".join(e.positional_part if positional else e.part for e in filter(predicate, self._elements))

    def partial(self, defaults: Mapping[str, Any]) -> "Format":
        """Get a partially formatted :meth:`fstring`.

        Args:
            defaults: Keys which should be replaced with real values. Keys which are **not** part of `defaults` will
                be left as-is.

        Returns:
            A partially formatted fstring.
        """
        parts, _ = parse_format_string.Element.parse_block(self._fmt, defaults=defaults)
        return Format("".join(parts))

    @staticmethod
    def parse(fmt: FormatType) -> "Format":
        """Parse a format.

        Args:
            fmt: Input to parse.

        Returns:
            A ``Format`` instance.
        """
        return fmt if isinstance(fmt, Format) else Format(fmt)

    @property
    def placeholders(self) -> PlaceholdersTuple:
        """All placeholders in the order in which they appear."""
        return self._extract_placeholders(self._elements)

    @property
    def required_placeholders(self) -> PlaceholdersTuple:
        """All required placeholders in the order in which they appear."""
        return self._extract_placeholders(filter(lambda e: e.required, self._elements))

    @property
    def optional_placeholders(self) -> PlaceholdersTuple:  # pragma: no cover
        """All optional placeholders in the order in which they appear."""
        return self._extract_placeholders(filter(lambda e: not e.required, self._elements))

    @staticmethod
    def _extract_placeholders(elements: Iterable[parse_format_string.Element]) -> PlaceholdersTuple:
        ans = []
        for e in elements:
            ans.extend(e.placeholders)
        return tuple(ans)

    def __repr__(self) -> str:
        return f"{tname(self)}({self._fmt!r})"
