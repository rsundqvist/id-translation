from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Generic

from rics.misc import tname

from ..transform.types import Transformer
from ..types import ID, IdType, NameType, SourceType
from ._format import Format
from ._magic_dict import MagicDict
from .types import PlaceholdersTuple, PlaceholderTranslations, TranslatedIds

if TYPE_CHECKING:
    import pandas


class FormatApplier(Generic[NameType, SourceType, IdType]):
    """Application of :class:`.Format` specifications.

    This class converts raw translation data into ready-to-use dicts on the form ``{id: translation}``, where the
    translation is always a plain string.

    Args:
        translations: A :class:`~.PlaceholderTranslations` object returned by fetchers.
        transformer: Initialized :class:`.Transformer` instance.

    Raises:
        ValueError: If `default` is given and any placeholder names are missing.

    Examples:
        Basic usage.

        >>> data = {1999: "Sofia", 1991: "Richard", 1904: "Fred"}
        >>> translations = PlaceholderTranslations.from_dict("my-source", data)
        >>> applier = FormatApplier(translations)

        We used the simplified ``{id: name}`` to create the translation object above. Let's create the formats to use:

        >>> fmt = Format.parse("{id}:{name}")
        >>> default_fmt = Format.parse("<Failed: id={id!r}>")

        Using ``FormatApplier.__call__`` delegates to :meth:`apply`.

        >>> applier(fmt, default_fmt=default_fmt)
        {1999: '1999:Sofia', 1991: '1991:Richard', 1904: '1904:Fred'}

        The output may look like a regular ``dict``, but is actually a :class:`.MagicDict`.

        >>> magic_dict = applier(fmt, default_fmt=default_fmt)
        >>> type(magic_dict)
        <class 'id_translation.offline._magic_dict.MagicDict'>

        .. warning::
            The :class:`.MagicDict` is does **not** behave like a regular dict.

        You can, for instance, use ``__getitem__`` on unknown keys:

        >>> magic_dict = applier(fmt, default_fmt=default_fmt)
        >>> magic_dict[-1]
        '<Failed: id=-1>'

        See the :class:`.MagicDict` class documentation for more information.
    """

    def __init__(
        self,
        translations: PlaceholderTranslations[SourceType],
        *,
        transformer: Transformer[IdType] | None = None,
    ) -> None:
        self._translations = translations
        self._source = translations.source
        self._placeholder_names = translations.placeholders
        self._n_ids = len(translations.records)
        self._transformer = transformer

    def apply(
        self,
        fmt: Format,
        *,
        default_fmt: Format,
        placeholders: PlaceholdersTuple | None = None,
        default_fmt_placeholders: dict[str, Any] | None = None,
        enable_uuid_heuristics: bool = True,
    ) -> MagicDict[IdType]:
        """Translate IDs.

        .. note::

           This method does not accept strings. Use :meth:`.Format.parse` to convert raw formats.

        Args:
            fmt: Translation :class:`.Format` to use.
            placeholders: Tuple of placeholder names to include in the formatted output. If ``None``, use the
                intersection of :attr:`.placeholders` and :attr:`fmt.placeholders <.Format.placeholders>`.
            default_fmt: Alternative format for default translation.
            default_fmt_placeholders: Default placeholders, e.g. ``{'name': 'default name'}``.
            enable_uuid_heuristics: Improves matching when :py:class:`~uuid.UUID`-like IDs are in use.

        Returns:
            A dict ``{id: translation}``.

        Notes:
            This method is an alias of ``__call__``.
        """
        assert isinstance(fmt, Format), f"invalid {fmt=}"  # noqa: S101
        assert isinstance(default_fmt, Format), f"invalid {default_fmt=}"  # noqa: S101

        if placeholders is None:
            # Use as many placeholders as possible.
            placeholders = tuple(filter(self._placeholder_names.__contains__, fmt.placeholders))

        fstring = fmt.fstring(placeholders, positional=True)
        real_translations = self._apply(fstring, placeholders)

        if default_fmt_placeholders is None:
            default_fmt_placeholders = {}

        partial = default_fmt.partial(default_fmt_placeholders)
        try:
            default_fstring = partial.fstring(positional=True)
        except KeyError as e:
            raise ValueError(
                f"All required placeholders except {{{ID}}} must be provided for {default_fmt=}:"
                f" {default_fmt.required_placeholders}."
            ) from e

        return MagicDict(real_translations, default_fstring, enable_uuid_heuristics, self._transformer)

    __call__ = apply

    def to_dict(self) -> dict[str, Sequence[Any]]:
        """Get the underlying data used for translations as a dict.

        Returns:
            A dict ``{placeholder: [values...]}``.
        """
        return self._translations.to_dict()

    def to_pandas(self) -> "pandas.DataFrame":
        """Get the underlying data used for translations as a :class:`pandas.DataFrame`."""
        from pandas import DataFrame  # noqa: PLC0415

        return DataFrame(self.to_dict()).convert_dtypes()

    @property
    def records(self) -> Sequence[Sequence[Any]]:
        """Records used by this instance; see :attr:`.PlaceholderTranslations.records`."""
        return self._translations.records

    def _apply(self, fstring: str, placeholders: PlaceholdersTuple) -> TranslatedIds[IdType]:
        """Apply fstring to all IDs.

        Args:
            fstring: A format string.
            placeholders: Keys needed for the fstring, in the order in which they appear.

        Returns:
            A dict ``{id: translation}``.
        """
        id_pos, records = self._translations.id_pos, self._translations.records

        if self._placeholder_names == placeholders:
            return {record[id_pos]: fstring.format(*record) for record in records}
        else:
            pos = tuple(map(self._placeholder_names.index, placeholders))
            return {record[id_pos]: fstring.format(*(record[i] for i in pos)) for record in records}

    @property
    def source(self) -> SourceType:
        """Return translation source."""
        return self._translations.source

    @property
    def placeholders(self) -> list[str]:
        """List of placeholder names; see :attr:`.PlaceholderTranslations.placeholders`."""
        return list(self._translations.placeholders)

    @property
    def transformer(self) -> Transformer[IdType] | None:
        """Get the :class:`.Transformer` instance (or ``None``) used by this ``FormatApplier``."""
        return self._transformer

    def __len__(self) -> int:
        return len(self._translations.records)

    def __repr__(self) -> str:
        placeholders = tuple(self._placeholder_names)
        source = self._source
        return f"{tname(self)}({len(self)} IDs, {placeholders=}, {source=})"
