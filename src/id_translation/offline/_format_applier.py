from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Generic

from ..exceptions import MissingPlaceholderError
from ..transform.types import Transformer
from ..types import ID, IdType, NameType, SourceType
from ._format import Format
from ._magic_dict import MagicDict
from .types import PlaceholdersTuple, PlaceholderTranslations, TranslatedIds, _id_position

if TYPE_CHECKING:
    import pandas


class FormatApplier(Generic[NameType, SourceType, IdType]):
    """Application of :class:`~id_translation.offline.Format` specifications.

    This class converts raw translation data into ready-to-use dicts on the form ``{id: translation}``, where the
    translation is always a plain string.

    Args:
        translations: A :class:`~id_translation.offline.types.PlaceholderTranslations` object returned by fetchers.
        transformer: Initialized :class:`~id_translation.transform.types.Transformer` instance.

    Examples:
        Basic usage.

        >>> data = {1999: "Sofia", 1991: "Richard", 1904: "Fred"}
        >>> translations = PlaceholderTranslations.from_dict("my-source", data)
        >>> applier = FormatApplier(translations)

        We used the simplified ``{id: name}`` to create the translation object above. Let's create the formats to use:

        >>> fmt = Format.parse("{id}:{name}")
        >>> default_fmt = Format.parse("<Failed: id={id!r}>")

        Using ``FormatApplier.__call__`` delegates to :meth:`~id_translation.offline.FormatApplier.apply`.

        >>> applier(fmt, default_fmt=default_fmt)
        {1999: '1999:Sofia', 1991: '1991:Richard', 1904: '1904:Fred'}

        The output may look like a regular ``dict``, but is actually a :class:`~id_translation.offline.MagicDict`.

        >>> magic_dict = applier(fmt, default_fmt=default_fmt)
        >>> type(magic_dict)
        <class 'id_translation.offline._magic_dict.MagicDict'>

        .. warning::
            The :class:`~id_translation.offline.MagicDict` is does **not** behave like a regular dict.

        You can, for instance, use ``__getitem__`` on unknown keys:

        >>> magic_dict = applier(fmt, default_fmt=default_fmt)
        >>> magic_dict[-1]
        '<Failed: id=-1>'

        See the :class:`~id_translation.offline.MagicDict` class documentation for more information.
    """

    def __init__(
        self,
        translations: PlaceholderTranslations[SourceType],
        *,
        transformer: Transformer[IdType] | None = None,
    ) -> None:
        self._translations = translations
        self._transformer = transformer
        self._id_pos = _id_position(translations)

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

           This method does not accept strings. Use :meth:`Format.parse <id_translation.offline.Format.parse>` to
           convert raw formats.

        Args:
            fmt: Translation :class:`~id_translation.offline.Format` to use.
            placeholders: Tuple of placeholder names to include in the formatted output. If ``None``, use the
                intersection of :attr:`~id_translation.offline.FormatApplier.placeholders` and
                :attr:`fmt.placeholders <id_translation.offline.Format.placeholders>`.
            default_fmt: Alternative format for default translation.
            default_fmt_placeholders: Default placeholders, e.g. ``{'name': 'default name'}``.
            enable_uuid_heuristics: Improves matching when :py:class:`~uuid.UUID`-like IDs are in use.

        Returns:
            A dict ``{id: translation}``.

        Raises:
            ~id_translation.exceptions.MissingPlaceholderError: If the translations lack a placeholder that `fmt`
                requires.

        Notes:
            This method is an alias of ``__call__``.
        """
        assert isinstance(fmt, Format), f"invalid {fmt=}"  # noqa: S101
        assert isinstance(default_fmt, Format), f"invalid {default_fmt=}"  # noqa: S101

        available = {*self._placeholders}
        available.update(
            actual for actual, wanted in self._translations.placeholder_aliases.items() if wanted in available
        )
        # Use as many placeholders as possible, including aliases. The fstring is positional, so keep the fmt order.
        include = available if placeholders is None else {*placeholders, *fmt.required_placeholders}
        placeholders = tuple(filter(include.__contains__, fmt.placeholders))

        missing = sorted({*fmt.required_placeholders, *placeholders}.difference(available))
        if missing:
            hints = ["If the source has them, they may not have been fetched."]
            if optional := "".join(f"[ {{{name}}}]" for name in missing if name in fmt.required_placeholders):
                hints.append(f"Placeholders that the source may lack can be marked optional: {optional!r}.")
            raise MissingPlaceholderError(
                f"Source {self.source!r} lacks placeholders {missing} for {fmt!r}; it has only"
                f" {sorted(self._placeholders)}.",
                missing_placeholders=missing,
                placeholders=self._placeholders,
                source=self.source,
                hints=hints,
            )

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
        """Records used by this instance.

        See :attr:`PlaceholderTranslations.records <id_translation.offline.types.PlaceholderTranslations.records>`.
        """
        return self._translations.records

    def _apply(self, fstring: str, placeholders: PlaceholdersTuple) -> TranslatedIds[IdType]:
        """Apply fstring to all IDs.

        Args:
            fstring: A format string.
            placeholders: Keys needed for the fstring, in the order in which they appear.

        Returns:
            A dict ``{id: translation}``.
        """
        id_pos, records = self._id_pos, self._translations.records

        if self._placeholders == placeholders:
            return {record[id_pos]: fstring.format(*record) for record in records}
        else:
            placeholders = tuple(self._translations.placeholder_aliases.get(p, p) for p in placeholders)
            pos = tuple(map(self._placeholders.index, placeholders))
            return {record[id_pos]: fstring.format(*(record[i] for i in pos)) for record in records}

    @property
    def _placeholders(self) -> PlaceholdersTuple:
        return self._translations.placeholders

    @property
    def source(self) -> SourceType:
        """Return translation source."""
        return self._translations.source

    @property
    def placeholders(self) -> list[str]:
        """List of placeholder names.

        See
        :attr:`PlaceholderTranslations.placeholders <id_translation.offline.types.PlaceholderTranslations.placeholders>`.
        """
        return list(self._placeholders)

    @property
    def transformer(self) -> Transformer[IdType] | None:
        """Get the :class:`~id_translation.transform.types.Transformer` instance (or ``None``) used by this ``FormatApplier``."""
        return self._transformer

    def __len__(self) -> int:
        return len(self._translations.records)

    def __repr__(self) -> str:
        placeholders = self._placeholders
        source = self.source
        return f"{self.__class__.__name__}({len(self)} IDs, {placeholders=}, {source=})"
