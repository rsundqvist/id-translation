from typing import Iterable, List

from rics.misc import tname

from . import parse_format_string
from .types import FormatType, PlaceholdersTuple


class Format:
    r"""Format specification for translations strings.

    Translation formats are similar to regular f-strings, with two important exceptions:

        1. Positional placeholders (``'{}'``) may not be used; correct form is ``'{placeholder-name}'``.
        2. Substrings surrounded by ``'[]'`` denote an optional element. Optional elements..

           * `Must` contain at least one placeholder.
           * Are rendered only if `all` of its placeholders are defined.
           * Are rendered `without` delimiting brackets.

     .. hint::

        Literal angle brackets are added by doubling the wanted character, as for ``'{'`` and ``'}'`` in plain Python
        f-strings. For example, ``'[['`` will render a ``'['``-literal.

    Args:
        fmt: A translation fstring.

    Examples:
        A format string with an optionl element.

        >>> from id_translation.offline import Format
        >>> fmt = Format('{id}:{name}[, nice={is_nice}]')

        The ``Format`` class when used directly only returns required placeholders by default..

        >>> fmt.fstring(), fmt.fstring().format(id=0, name='Tarzan')
        ('{id}:{name}', '0:Tarzan')

        ..but the `placeholders` attribute can be used to retrieve all placeholders, required and optional:

        >>> fmt.placeholders
        ('id', 'name', 'is_nice')
        >>> fmt.fstring(fmt.placeholders), fmt.fstring(fmt.placeholders).format(id=1, name='Morris', is_nice=True)
        ('{id}:{name}, nice={is_nice}', '1:Morris, nice=True')
    """

    def __init__(self, fmt: str) -> None:
        self._fmt = fmt
        self._elements: List[parse_format_string.Element] = self._parse_format_string(fmt)

    def fstring(self, placeholders: Iterable[str] = None, positional: bool = False) -> str:
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

    @classmethod
    def _parse_format_string(cls, format_string: str) -> List[parse_format_string.Element]:
        return parse_format_string.get_elements(format_string)

    def __repr__(self) -> str:
        def repr_part(e: parse_format_string.Element) -> str:
            s = e.part.replace("[", "[[").replace("]", "]]")
            return s if e.required else f"[{s}]"

        return f"{tname(self)}('{''.join(map(repr_part, self._elements))}')"
