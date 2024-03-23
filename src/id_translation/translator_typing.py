"""Types that are specific to the :class:`id_translation.Translator` implementation."""

import typing as _t

from rics.collections.dicts import MakeType as _MakeType

from . import types as _tt
from .fetching import Fetcher as _Fetcher
from .mapping import Mapper as _Mapper
from .mapping.types import UserOverrideFunction as _UserOverrideFunction
from .offline import TranslationMap as _TranslationMap
from .offline import types as _ot
from .transform.types import Transformer as _Transformer

SimpleDictFetcherTypes = dict[_tt.SourceType, dict[_tt.IdType, str]]
"""Data for translating using only the default `id` and `name` placeholders.

Must be on the form ``{source: {id: name}``.
"""

SourceToPlaceholderTranslationsMakeTypes = _t.Mapping[_tt.SourceType, _ot.MakeTypes[_tt.SourceType]]
"""Data for translating using arbitrary placeholders; see :meth:`.PlaceholderTranslations.make`"""

NativeFetcherTypes = (
    _TranslationMap[_tt.NameType, _tt.SourceType, _tt.IdType]
    | _Fetcher[_tt.SourceType, _tt.IdType]
    | _ot.SourcePlaceholderTranslations[_tt.SourceType]
)
"""Internal types related to fetching."""

FetcherTypes = (
    NativeFetcherTypes[_tt.NameType, _tt.SourceType, _tt.IdType]
    | SimpleDictFetcherTypes[_tt.SourceType, _tt.IdType]
    | SourceToPlaceholderTranslationsMakeTypes[_tt.SourceType]
)
"""All valid input types for creating a ``Translator``."""


class CopyParams(_t.TypedDict, _t.Generic[_tt.NameType, _tt.SourceType, _tt.IdType], total=False):
    """Arguments of :meth:`.Translator.copy`.

    Usage example: ``**kwargs: typing.Unpack[CopyParams]``.
    """

    fetcher: FetcherTypes[_tt.NameType, _tt.SourceType, _tt.IdType]
    fmt: _ot.FormatType
    mapper: _Mapper[_tt.NameType, _tt.SourceType, None]
    default_fmt: _ot.FormatType
    default_fmt_placeholders: _MakeType[_tt.SourceType, str, _t.Any]
    enable_uuid_heuristics: bool
    transformers: dict[_tt.SourceType, _Transformer[_tt.IdType]] | None


class TranslateParams(_t.TypedDict, _t.Generic[_tt.NameType, _tt.SourceType, _tt.IdType], total=False):
    """Keyword arguments of :meth:`.Translator.translate`.

    .. note::

       Does not include `translatable`.

    Usage example: ``**kwargs: typing.Unpack[TranslateParams]``.
    """

    names: _tt.NameTypes[_tt.NameType] | _tt.NameToSource[_tt.NameType, _tt.SourceType] | None
    ignore_names: _tt.Names[_tt.NameType] | None
    inplace: bool
    override_function: _UserOverrideFunction[_tt.NameType, _tt.SourceType, None]
    maximal_untranslated_fraction: float
    reverse: bool
    fmt: _ot.FormatType | None
