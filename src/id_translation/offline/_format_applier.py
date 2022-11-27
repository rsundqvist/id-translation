from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, List

from rics.misc import tname

from ..types import ID, IdType, NameType, SourceType
from ._format import Format
from ._magic_dict import MagicDict
from .types import PlaceholdersTuple, PlaceholderTranslations, TranslatedIds


class FormatApplier(ABC, Generic[NameType, SourceType, IdType]):
    """Base class for application of ``Format`` specifications.

    Args:
        translations: Matrix of ID translation components returned by fetchers.

    Raises:
        ValueError: If `default` is given and any placeholder names are missing.
    """

    def __init__(self, translations: PlaceholderTranslations[SourceType]) -> None:
        self._source = translations.source
        self._placeholder_names = translations.placeholders
        self._n_ids = len(translations.records)

    def __call__(
        self,
        fmt: Format,
        placeholders: PlaceholdersTuple = None,
        default_fmt: Format = None,
        default_fmt_placeholders: Dict[str, Any] = None,
    ) -> MagicDict[IdType]:
        """Translate IDs.

        Args:
            fmt: Translation format to use.
            placeholders: Placeholders to include in the formatted output. Use as many as possible if ``None``.
            default_fmt: Alternative format for default translation.
            default_fmt_placeholders: Default placeholders

        Returns:
            A dict ``{idx: translated_id}``.
        """
        if placeholders is None:
            # Use as many placeholders as possible.
            placeholders = tuple(filter(self._placeholder_names.__contains__, fmt.placeholders))

        fstring = fmt.fstring(placeholders, self.positional)
        real_translations = self._apply(fstring, placeholders)

        if default_fmt or default_fmt_placeholders:
            fmap = {ID: "{}", **(default_fmt_placeholders or {})}
            default_fstring = (default_fmt or fmt).fstring(fmap, positional=False).format(**fmap)
        else:
            default_fstring = None

        return MagicDict(
            real_translations,
            default_fstring,
        )

    @abstractmethod
    def _apply(self, fstring: str, placeholders: PlaceholdersTuple) -> TranslatedIds[IdType]:
        """Apply fstring to all IDs.

        The abstract class delegates ``__apply__``-invocations to this method after some input validation.

        Args:
            fstring: A format string.
            placeholders: Keys needed for the fstring, in the order in which they appear.

        Returns:
            A dict ``{idx: translated_id}``.
        """

    @property
    def positional(self) -> bool:
        """If ``True``, names are stripped from fstring placeholders."""
        return True

    @property
    def source(self) -> SourceType:
        """Return translation source."""
        return self._source  # pragma: no cover

    @property
    def placeholders(self) -> List[str]:
        """Return placeholder names in sorted order."""
        return list(self._placeholder_names)  # pragma: no cover

    def __len__(self) -> int:
        return self._n_ids  # pragma: no cover

    def __repr__(self) -> str:
        placeholders = tuple(self._placeholder_names)
        source = self._source
        return f"{tname(self)}({len(self)} IDs, {placeholders=}, {source=})"


class DefaultFormatApplier(FormatApplier[NameType, SourceType, IdType]):
    """Default format applier implementation."""

    def __init__(
        self,
        translations: PlaceholderTranslations[SourceType],
    ) -> None:
        super().__init__(translations)
        self._pht = translations

    def _apply(self, fstring: str, placeholders: PlaceholdersTuple) -> TranslatedIds[IdType]:
        if self._placeholder_names == placeholders:
            return {record[self._pht.id_pos]: fstring.format(*record) for record in self._pht.records}
        else:
            pos = tuple(map(self._placeholder_names.index, placeholders))
            return {record[self._pht.id_pos]: fstring.format(*(record[i] for i in pos)) for record in self._pht.records}
