from collections.abc import Iterator, Mapping, Sequence
from copy import copy
from typing import TYPE_CHECKING, Any, Generic, Self, Union

from rics.collections.dicts import InheritedKeysDict, reverse_dict
from rics.misc import tname

from ..transform.types import Transformer, Transformers
from ..types import HasSources, IdType, NameToSource, NameType, SourceType
from ._format import Format
from ._format_applier import FormatApplier
from ._magic_dict import MagicDict
from .types import FormatType, PlaceholderTranslations, SourcePlaceholderTranslations

if TYPE_CHECKING:
    import pandas


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
        transformers: A dict ``{source: transformer}`` of initialized :class:`.Transformer` instances.

    """

    def __init__(
        self,
        source_translations: SourcePlaceholderTranslations[SourceType],
        *,
        fmt: FormatType = Format.DEFAULT,
        default_fmt: FormatType = Format.DEFAULT_FAILED,
        name_to_source: NameToSource[NameType, SourceType] | None = None,
        default_fmt_placeholders: InheritedKeysDict[SourceType, str, Any] | None = None,
        enable_uuid_heuristics: bool = True,
        transformers: Transformers[SourceType, IdType] | None = None,
    ) -> None:
        self.fmt = Format.parse(fmt)
        self.default_fmt = Format.parse(default_fmt)
        self.default_fmt_placeholders = default_fmt_placeholders or InheritedKeysDict.make({})

        transformers = transformers or {}
        self._format_appliers: dict[SourceType, FormatApplier[NameType, SourceType, IdType]] = {
            source: FormatApplier(translations, transformer=transformers.get(source))
            for source, translations in source_translations.items()
        }
        self._names_and_sources: set[NameType | SourceType] = set()
        self.name_to_source = name_to_source or {}

        self._reverse_mode: bool = False
        self.enable_uuid_heuristics = enable_uuid_heuristics

    def to_dicts(self) -> dict[SourceType, dict[str, Sequence[Any]]]:
        """Get the underlying data used for translations as dicts.

        This is equivalent using :meth:`to_pandas`, then calling ``DataFrame.to_dict(orient='list')`` on each frame.

        Returns:
            A dict ``{source: {placeholder: [values...]}}``.
        """
        return {applier.source: applier.to_dict() for applier in self._format_appliers.values()}

    def to_pandas(self) -> dict[SourceType, "pandas.DataFrame"]:
        """Get the underlying data used for translations as :class:`pandas.DataFrame`.

        Returns:
            A dict ``{source: DataFrame}``.
        """
        return {applier.source: applier.to_pandas() for applier in self._format_appliers.values()}

    def to_translations(self, fmt: FormatType = None) -> dict[SourceType, MagicDict[IdType]]:
        """Create translations for all sources.

        Returned values are of type :class:`.MagicDict`. To convert to regular built-in dicts, run

        .. code-block::

           translations = translation_map.to_translations()
           as_regular_dicts = {
              source: dict(magic)
              for source, magic in translations.items()
           }

        on the returned dict-of-magic-dicts.

        Args:
            fmt: :class:`.Format` to use. If ``None``, fall back to init format.

        Returns:
            A dict of translations ``{source: MagicDict}``.
        """
        return {source: self.apply(source, fmt=fmt) for source in self.sources}

    @classmethod
    def from_pandas(
        cls,
        frames: dict[SourceType, "pandas.DataFrame"],
        fmt: FormatType = Format.DEFAULT,
        *,
        default_fmt: FormatType = Format.DEFAULT_FAILED,
    ) -> Self:
        """Create a new instance from a :class:`pandas.DataFrame` dict.

        Args:
            frames: A dict ``{source: DataFrame}``.
            fmt: A translation format. Must be given to use as a mapping.
            default_fmt: Alternative format specification to use instead of `fmt` for fallback translation.

        Returns:
            A new ``TranslationMap``.
        """
        source_translations = {
            source: PlaceholderTranslations.from_dataframe(source, frame) for source, frame in frames.items()
        }
        return cls(source_translations, fmt=fmt, default_fmt=default_fmt)

    def apply(
        self,
        name_or_source: NameType | SourceType,
        fmt: FormatType | None = None,
        *,
        default_fmt: FormatType | None = None,
    ) -> MagicDict[IdType]:
        """Create translations for a given name or source.

        Args:
            name_or_source: A name or source to translate.
            fmt: :class:`.Format` to use. If ``None``, fall back to init format.
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
                reverse_dict(translations, duplicate_key_action="raise"),  # type: ignore
                default_value=default_fmt.fstring(positional=True),
                enable_uuid_heuristics=False,
            )
            if self.reverse_mode
            else translations
        )

    @property
    def names(self) -> list[NameType]:
        """Return names that can be translated."""
        return list(self.name_to_source)

    @property
    def sources(self) -> list[SourceType]:
        return list(self._format_appliers)

    @property
    def placeholders(self) -> dict[SourceType, list[str]]:
        return {applier.source: applier.placeholders for applier in self._format_appliers.values()}

    @property
    def name_to_source(self) -> NameToSource[NameType, SourceType]:
        """Return name-to-source mapping."""
        return dict(self._name_to_source)

    @name_to_source.setter
    def name_to_source(self, value: NameToSource[NameType, SourceType]) -> None:
        self._name_to_source: NameToSource[NameType, SourceType] = value
        self._names_and_sources = set(value).union(self._format_appliers)

    @property
    def fmt(self) -> Format:
        """Return the translation format."""
        return self._fmt

    @fmt.setter
    def fmt(self, value: FormatType) -> None:
        self._fmt = Format.parse(value)

    @property
    def default_fmt(self) -> Format:
        """Return the format specification to use instead of :attr:`fmt` for fallback translation."""
        return self._default_fmt

    @default_fmt.setter
    def default_fmt(self, value: FormatType) -> None:
        self._default_fmt = Format.parse(value)

    @property
    def default_fmt_placeholders(self) -> InheritedKeysDict[SourceType, str, Any]:
        """Return the default translations used for `default_fmt_placeholders` placeholders."""
        return self._default_fmt_placeholders

    @default_fmt_placeholders.setter
    def default_fmt_placeholders(self, value: InheritedKeysDict[SourceType, str, Any]) -> None:
        self._default_fmt_placeholders = InheritedKeysDict.make(value) if value else InheritedKeysDict()

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

    @property
    def transformers(self) -> dict[SourceType, Transformer[IdType]]:
        """Get a dict ``{source: transformer}`` of :class:`.Transformer` instances used by this ``TranslationMap``."""
        return {
            source: applier.transformer
            for source, applier in self._format_appliers.items()
            if applier.transformer is not None
        }

    def copy(self) -> Self:
        """Make a copy of this ``TranslationMap``."""
        return copy(self)

    def __getitem__(self, name_or_source: NameType | SourceType) -> MagicDict[IdType]:
        return self.apply(name_or_source)

    def __len__(self) -> int:
        return len(self._names_and_sources)

    def __iter__(self) -> Iterator[NameType | SourceType]:
        return iter(self._names_and_sources)

    def __bool__(self) -> bool:
        return bool(self._format_appliers)

    def __repr__(self) -> str:
        sources = ", ".join(
            f"'{formatter.source}': {len(formatter)} IDs" for formatter in self._format_appliers.values()
        )
        return f"{tname(self)}({sources})"
