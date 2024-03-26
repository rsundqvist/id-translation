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
    """Application of ``Format`` specifications.

    Args:
        translations: Matrix of ID translation components returned by fetchers.
        transformer: Initialized :class:`.Transformer` instance.

    Raises:
        ValueError: If `default` is given and any placeholder names are missing.
    """

    def __init__(
        self, translations: PlaceholderTranslations[SourceType], *, transformer: Transformer[IdType] = None
    ) -> None:
        self._translations = translations
        self._source = translations.source
        self._placeholder_names = translations.placeholders
        self._n_ids = len(translations.records)
        self._transformer = transformer

    def __call__(
        self,
        fmt: Format,
        *,
        default_fmt: Format,
        placeholders: PlaceholdersTuple | None = None,
        default_fmt_placeholders: dict[str, Any] | None = None,
        enable_uuid_heuristics: bool = True,
    ) -> MagicDict[IdType]:
        """Translate IDs.

        Args:
            fmt: Translation format to use.
            placeholders: Placeholders to include in the formatted output. Use as many as possible if ``None``.
            default_fmt: Alternative format for default translation.
            default_fmt_placeholders: Default placeholders.
            enable_uuid_heuristics: Enabling may improve matching when :py:class:`~uuid.UUID`-like IDs are in use.

        Returns:
            A dict ``{idx: translated_id}``.
        """
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

    def to_dict(self) -> dict[str, Sequence[Any]]:
        """Get the underlying data used for translations as a dict.

        Returns:
            A dict ``{placeholder: [values...]}``.
        """
        return self._translations.to_dict()

    def to_pandas(self) -> "pandas.DataFrame":
        """Get the underlying data used for translations as a :class:`pandas.DataFrame`."""
        from pandas import DataFrame

        return DataFrame(self.to_dict()).convert_dtypes()

    @property
    def records(self) -> Sequence[Sequence[Any]]:
        """Records used by this instance."""
        return self._translations.records

    def _apply(self, fstring: str, placeholders: PlaceholdersTuple) -> TranslatedIds[IdType]:
        """Apply fstring to all IDs.

        The abstract class delegates ``__apply__``-invocations to this method after some input validation.

        Args:
            fstring: A format string.
            placeholders: Keys needed for the fstring, in the order in which they appear.

        Returns:
            A dict ``{idx: translated_id}``.
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
        """Return placeholder names in sorted order."""
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
