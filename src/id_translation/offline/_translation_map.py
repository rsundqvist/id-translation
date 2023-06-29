from copy import copy
from typing import Any, Dict, Generic, Iterator, List, Mapping, Optional, Set, Union

from rics.collections.dicts import InheritedKeysDict, reverse_dict
from rics.misc import tname

from ..types import HasSources, IdType, NameToSource, NameType, SourceType
from ._format import Format
from ._format_applier import FormatApplier
from ._magic_dict import MagicDict
from .types import FormatType, SourcePlaceholderTranslations


class TranslationMap(
    Generic[NameType, SourceType, IdType],
    HasSources[SourceType],
    Mapping[Union[NameType, SourceType], MagicDict[IdType]],
):
    """Storage class for fetched translations.

    Args:
        source_translations: Fetched translations ``{source: PlaceholderTranslations}``.
        name_to_source: Mappings ``{name: source}``, but may be overridden by the user.
        fmt: A translation format. Must be given to use as a mapping.
        default_fmt: Alternative format specification to use instead of `fmt` for fallback translation.
        default_fmt_placeholders: Per-source default placeholder values.
        enable_uuid_heuristics: Enabling may improve matching when :py:class:`~uuid.UUID`-like IDs are in use.

    Notes:
        Type checking of `fmt` and `default_fmt_placeholders` attributes may fail due to
        `mypy#3004 <https://github.com/python/mypy/issues/3004>`_
    """

    def __init__(
        self,
        source_translations: SourcePlaceholderTranslations[SourceType],
        name_to_source: NameToSource[NameType, SourceType] = None,
        fmt: FormatType = None,
        default_fmt: FormatType = None,
        default_fmt_placeholders: InheritedKeysDict[SourceType, str, Any] = None,
        enable_uuid_heuristics: bool = True,
    ) -> None:
        self.default_fmt = default_fmt  # type: ignore
        self.default_fmt_placeholders = default_fmt_placeholders  # type: ignore
        self.fmt = fmt  # type: ignore
        self._format_appliers: Dict[SourceType, FormatApplier[NameType, SourceType, IdType]] = {
            source: FormatApplier(translations) for source, translations in source_translations.items()
        }
        self._names_and_sources: Set[Union[NameType, SourceType]] = set()
        self.name_to_source = name_to_source or {}

        self._reverse_mode: bool = False
        self.enable_uuid_heuristics = enable_uuid_heuristics

    def apply(
        self, name_or_source: Union[NameType, SourceType], fmt: FormatType = None, default_fmt: FormatType = None
    ) -> MagicDict[IdType]:
        """Create translations for a given name or source.

        Args:
            name_or_source: A name or source to translate.
            fmt: Format to use. If ``None``, fall back to init format.
            default_fmt: Alternative format for default translation. Resolution: Arg -> init arg, fmt arg, init fmt arg

        Returns:
            Translations for `name` as a dict ``{id: translation}``.

        Raises:
            ValueError: If ``fmt=None`` and initialized without `fmt`.
            KeyError: If trying to translate `name` which is not known.

        Notes:
             This method is called by ``__getitem__``.
        """
        fmt = self._fmt if fmt is None else fmt
        if fmt is None:
            raise ValueError("No format specified and None given at initialization.")  # pragma: no cover

        fmt = Format.parse(fmt)
        default_fmt = self._default_fmt if default_fmt is None else Format.parse(default_fmt)
        source = self.name_to_source.get(name_or_source, name_or_source)  # type: ignore
        translations: MagicDict[IdType] = self._format_appliers[source](
            fmt,
            default_fmt=default_fmt,
            default_fmt_placeholders=self.default_fmt_placeholders.get(source),
            enable_uuid_heuristics=self.enable_uuid_heuristics,
        )
        return (
            MagicDict(
                reverse_dict(translations),  # type: ignore
                default_value=None,  # force failure for unknown keys
                enable_uuid_heuristics=False,
            )
            if self.reverse_mode
            else translations
        )

    @property
    def names(self) -> List[NameType]:
        """Return names that can be translated."""
        return list(self.name_to_source)

    @property
    def sources(self) -> List[SourceType]:
        return list(self._format_appliers)

    @property
    def placeholders(self) -> Dict[SourceType, List[str]]:
        return {applier.source: applier.placeholders for applier in self._format_appliers.values()}

    @property
    def name_to_source(self) -> NameToSource[NameType, SourceType]:
        """Return name-to-source mapping."""
        return self._name_to_source

    @name_to_source.setter
    def name_to_source(self, value: NameToSource[NameType, SourceType]) -> None:
        self._name_to_source: NameToSource[NameType, SourceType] = value
        self._names_and_sources = set(value).union(self._format_appliers)

    @property
    def fmt(self) -> Optional[Format]:
        """Return the translation format."""
        return self._fmt

    @fmt.setter
    def fmt(self, value: Optional[FormatType]) -> None:
        self._fmt = None if value is None else Format.parse(value)

    @property
    def default_fmt(self) -> Optional[Format]:
        """Return the format specification to use instead of `fmt` for fallback translation."""
        return self._default_fmt

    @default_fmt.setter
    def default_fmt(self, value: Optional[FormatType]) -> None:
        self._default_fmt = None if value is None else Format.parse(value)

    @property
    def default_fmt_placeholders(self) -> InheritedKeysDict[SourceType, str, Any]:
        """Return the default translations used for `default_fmt_placeholders` placeholders."""
        return self._default_fmt_placeholders

    @default_fmt_placeholders.setter
    def default_fmt_placeholders(self, value: Optional[InheritedKeysDict[SourceType, str, Any]]) -> None:
        self._default_fmt_placeholders = InheritedKeysDict() if value is None else InheritedKeysDict.make(value)

    @property
    def reverse_mode(self) -> bool:
        """Return reversed mode status flag.

         If set, the mappings returned by :meth:`apply` (and therefore also ``__getitem__``) are reversed.

        Returns:
            Reversal status flag.
        """
        return self._reverse_mode

    @reverse_mode.setter
    def reverse_mode(self, value: bool) -> None:
        self._reverse_mode = value

    @property
    def enable_uuid_heuristics(self) -> bool:
        """Return automatic UUID mitigation status."""
        return self._enable_uuid_heuristics

    @enable_uuid_heuristics.setter
    def enable_uuid_heuristics(self, value: bool) -> None:
        self._enable_uuid_heuristics = value

    def copy(self) -> "TranslationMap[NameType, SourceType, IdType]":
        """Make a copy of this ``TranslationMap``."""
        return copy(self)

    def __getitem__(self, name_or_source: Union[NameType, SourceType]) -> MagicDict[IdType]:
        return self.apply(name_or_source)

    def __len__(self) -> int:
        return len(self._names_and_sources)

    def __iter__(self) -> Iterator[Union[NameType, SourceType]]:
        return iter(self._names_and_sources)

    def __bool__(self) -> bool:
        return bool(self._format_appliers)

    def __repr__(self) -> str:
        sources = ", ".join(
            {f"'{formatter.source}': {len(formatter)} IDs" for formatter in self._format_appliers.values()}
        )
        return f"{tname(self)}({sources})"
