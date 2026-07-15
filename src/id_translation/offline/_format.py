from collections.abc import Iterable, Mapping
from typing import Any, Literal, Self

from rics.misc import tname

from .parse_format_string import Element, get_elements
from .types import PlaceholderAttributes, PlaceholdersTuple


class Format:
    """Format specification for translation strings.

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
        **Basic usage**

        Formats are created by passing a single ``str`` arguments, as described above.

        >>> Format(Format.DEFAULT)
        "Format('{id}:{name}')"
        >>> Format(Format.DEFAULT).fstring().format(id=1, name="First")
        '1:First'

        Using :meth:`Format.fstring <id_translation.offline.Format.fstring>` and :py:meth:`str.format` is flexible but verbose. Formats can be applied
        either
        through :meth:`Format.format <id_translation.offline.Format.format>`...

        >>> fmt = Format(Format.DEFAULT_FAILED)
        >>> fmt.format(id=1, name="First")

        ...or just ``Format.__call__()``.

        >>> fmt(id=1, name="First")
        '<Failed: id=1>'

        Using either convenience method will use as many placeholders as possible.

        >>> fmt = Format(Format.DEFAULT)
        >>> fmt.placeholders
        "('id', 'name')"
        >>> fmt(id=1, name="First")
        '1:First'
        >>> fmt(id=1, name="First", unknown=20.19)
        '1:First'

        Unknown placeholders are simply ignored.

        **Optional placeholders**

        A format string using literal angle brackets and an optional element.

        >>> from id_translation.offline import Format
        >>> fmt = Format("{id}:[[{name}]][, nice={is_nice}]")

        The ``Format`` class when used directly only returns required placeholders by default...

        >>> fmt.fstring()
        '{id}:[{name}]'
        >>> fmt(id=0, name="Tarzan")
        '0:[Tarzan]'

        ...but the :attr:`~id_translation.offline.Format.placeholders` attribute can be used to retrieve all placeholders, required and optional:

        >>> fmt.placeholders
        ('id', 'name', 'is_nice')
        >>> fmt(id=1, name="Morris", is_nice=True)
        '1:[Morris], nice=True'

    The :class:`~id_translation.Translator` will automatically add optional placeholders, if they are present in the source.

    .. note::
       Python format specifications and conversions are preserved.

    This is especially useful for long values such as UUIDs.

    >>> from uuid import UUID
    >>> uuid = UUID("550e8400-e29b-41d4-a716-446655440000")

    Convert to string and truncate to eight characters.

    >>> Format("{id!s:.8}:{name!r}").format(id=uuid, name="Sofia")
    "550e8400:'Sofia'"

    See the official :py:ref:`formatspec` documentation for details.
    """

    DEFAULT: Literal["{id}:{name}"] = "{id}:{name}"
    """Default translation format."""

    DEFAULT_FAILED: Literal["<Failed: id={id!r}>"] = "<Failed: id={id!r}>"
    """Default format for missing IDs."""

    def __init__(self, fmt: str) -> None:
        self._fmt = fmt
        self._elements: list[Element] = get_elements(fmt)

    def format(self, **placeholders: Any) -> str:
        """Apply the format.

        Args:
            **placeholders: Values to use for formatting.

        Returns:
            Formatting using `placeholders`.
        """
        return self.fstring(placeholders, positional=False).format_map(placeholders)

    __call__ = format

    def fstring(self, placeholders: Iterable[str] | None = None, *, positional: bool = False) -> str:
        """Create a format string for the given placeholders.

        Args:
            placeholders: Keys to keep. Passing ``None`` is equivalent to passing :attr:`~id_translation.offline.Format.required_placeholders`.
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
        def predicate(e: Element) -> bool:
            return e.required or set(placeholders).issuperset(e.placeholders)

        return "".join(e.positional_part if positional else e.part for e in filter(predicate, self._elements))

    def partial(self, defaults: Mapping[str, Any]) -> Self:
        """Get a partially formatted :meth:`~id_translation.offline.Format.fstring`.

        Args:
            defaults: Keys which should be replaced with real values. Keys which are **not** part of `defaults` will
                be left as-is.

        Returns:
            A partially formatted fstring.
        """
        new_fmt = Element.parse_block(self._fmt, defaults=defaults).parsed_block
        cls = type(self)
        return cls(new_fmt)

    @classmethod
    def parse(cls, fmt: str | Self) -> Self:
        """Parse a format.

        Args:
            fmt: A ``str`` or ``Format`` instance.

        Returns:
            A ``Format`` instance.
        """
        return cls(fmt) if isinstance(fmt, str) else fmt

    @property
    def placeholders(self) -> PlaceholdersTuple:
        """All placeholders in the order in which they appear."""
        return self._extract_placeholders(self._elements)

    @property
    def placeholder_attributes(self) -> PlaceholderAttributes:
        """Attribute access paths per placeholder.

        .. note::

           Includes indexing operations. See the :ref:`🚀 examples page
           <orm_example>` for usage.

        Returns:
            A dict ``{placeholder: {attribute, ...}}``.

        Examples:
            Basic attribute access.

            >>> fmt = "{id}:{name} | {id.__class__} | {name.__class__.does_not_exist}"
            >>> Format(fmt).placeholder_attributes
            {'id': {'__class__'}, 'name': {'__class__.does_not_exist'}}

            The ``Format`` does not validate properties, so this will raise an :class:`AttributeError` when translation
            strings are created.

            Nested attributes and mixed indexing.

            >>> fmt = "{user.name.first} {user.address[zip]} {items[0].name}"
            >>> {k: sorted(v) for k, v in Format(fmt).placeholder_attributes.items()}
            {'user': ['address[zip]', 'name.first'], 'items': ['[0].name']}

            Multiple indexes and deeper nesting.

            >>> fmt = "{a[0][1]} {b.c[2].d}"
            >>> {k: sorted(v) for k, v in Format(fmt).placeholder_attributes.items()}
            {'a': ['[0][1]'], 'b': ['c[2].d']}

            As seen above, indexing on the placeholder itself adds a level to the attribute path.
        """
        rv: PlaceholderAttributes = {}
        for e in self._elements:
            for placeholder, attribute in e.placeholder_attributes:
                rv.setdefault(placeholder, set()).add(attribute)
        return rv

    @property
    def required_placeholders(self) -> PlaceholdersTuple:
        """All required placeholders in the order in which they appear."""
        return self._extract_placeholders(filter(lambda e: e.required, self._elements))

    @property
    def optional_placeholders(self) -> PlaceholdersTuple:  # pragma: no cover
        """All optional placeholders in the order in which they appear."""
        return self._extract_placeholders(filter(lambda e: not e.required, self._elements))

    @staticmethod
    def _extract_placeholders(elements: Iterable[Element]) -> PlaceholdersTuple:
        ans = []
        for e in elements:
            ans.extend(e.placeholders)
        return tuple(ans)

    def __repr__(self) -> str:
        return f"{tname(self)}({self._fmt!r})"
