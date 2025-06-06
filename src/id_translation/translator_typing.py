"""Types that are specific to the :class:`id_translation.Translator` implementation."""

import typing as _t
from collections import abc as _abc

from rics.collections.dicts import MakeType as _MakeType

from . import types as _tt
from .fetching import CacheAccess as _CacheAccess
from .fetching import Fetcher as _Fetcher
from .mapping import Mapper as _Mapper
from .mapping.types import UserOverrideFunction as _UserOverrideFunction
from .offline import TranslationMap as _TranslationMap
from .offline import types as _ot
from .transform.types import Transformer as _Transformer

SimpleDictFetcherTypes = dict[_tt.SourceType, dict[_tt.IdType, str]]
"""Data for translating using only the default `id` and `name` placeholders.

Must be on the form ``{source: {id: name}}``.
"""

SourceToPlaceholderTranslationsMakeTypes = _abc.Mapping[_tt.SourceType, _ot.MakeTypes[_tt.SourceType, _tt.IdType]]
"""Data for translating using arbitrary placeholders; see :meth:`.PlaceholderTranslations.make`"""

NativeFetcherTypes: _t.TypeAlias = (
    _TranslationMap[_tt.NameType, _tt.SourceType, _tt.IdType]
    | _Fetcher[_tt.SourceType, _tt.IdType]
    | _ot.SourcePlaceholderTranslations[_tt.SourceType]
)
"""Internal types related to fetching."""

FetcherTypes: _t.TypeAlias = (
    NativeFetcherTypes[_tt.NameType, _tt.SourceType, _tt.IdType]
    | SimpleDictFetcherTypes[_tt.SourceType, _tt.IdType]
    | SourceToPlaceholderTranslationsMakeTypes[_tt.SourceType, _tt.IdType]
)
"""All valid input types for creating a ``Translator``."""


class AbstractFetcherParams(_t.TypedDict, _t.Generic[_tt.SourceType, _tt.IdType], total=False):
    """Keyword arguments for the :class:`.AbstractFetcher` base class."""

    mapper: _Mapper[str, str, _tt.SourceType] | None
    allow_fetch_all: bool
    selective_fetch_all: bool
    identifiers: _abc.Sequence[str] | None
    optional: bool
    cache_access: _CacheAccess[_tt.SourceType, _tt.IdType] | None


class MapParams(_t.TypedDict, _t.Generic[_tt.NameType, _tt.SourceType, _tt.IdType], total=False):
    """Arguments of :meth:`.Translator.map` and :meth:`.Translator.map_scores`."""

    translatable: _t.Required[_tt.Translatable[_tt.NameType, _tt.IdType]]
    names: _tt.NameTypes[_tt.NameType] | None
    ignore_names: _tt.Names[_tt.NameType] | None
    override_function: _UserOverrideFunction[_tt.NameType, _tt.SourceType, None] | None


class UniqueCopyParams(_t.TypedDict, _t.Generic[_tt.NameType, _tt.SourceType, _tt.IdType], total=False):
    """Arguments of :meth:`.Translator.copy` that do not overlap with :class:`AllTranslateParams`."""

    fetcher: FetcherTypes[_tt.NameType, _tt.SourceType, _tt.IdType]
    mapper: _Mapper[_tt.NameType, _tt.SourceType, None]
    default_fmt: _ot.FormatType
    default_fmt_placeholders: _MakeType[_tt.SourceType, str, _t.Any] | None
    enable_uuid_heuristics: bool
    transformers: dict[_tt.SourceType, _Transformer[_tt.IdType]] | None


class CopyParams(UniqueCopyParams[_tt.NameType, _tt.SourceType, _tt.IdType], total=False):
    """All arguments of :meth:`.Translator.copy`."""

    fmt: _ot.FormatType


class TranslateParams(_t.TypedDict, _t.Generic[_tt.NameType, _tt.SourceType, _tt.IdType], total=False):
    """Keyword arguments of :meth:`.Translator.translate`.

    .. note::

       Does not include `translatable` or `copy`.


    **Motivation**

    Allowing these to be passed as keyword arguments causes issues with typing, especially method overloading. For
    example:

    .. code-block::

       def func(**kwargs: Unpack[AllTranslateParams]):
          translatable = kwargs["translatable"]
          if isinstance(translatable, list) and kwargs.get(copy, True):
              raise CustomException("we don't do that here")

          else:
              # Do whatever

    using :class:`AllTranslateParams` is typically not as safe as:

    .. code-block::

       @overload
       def func(...): ...

       @overload
       def func(
           translatable: list, copy: Literal[False],
           **kwargs: Unpack[TranslateParams]
       ) -> Never: ...

       def func(translatable, copy, **kwargs: Unpack[TranslateParams]):
           "Implementation as above"

    since ``func(translatable=[], copy=False)`` does not behave like
    ``Translator.translate([], copy=False)`` would. Functions that transparently wrap
    :meth:`.Translator.translate` should probably use :py:func:`functools.wraps` instead.
    """

    names: _tt.NameTypes[_tt.NameType] | _tt.NameToSource[_tt.NameType, _tt.SourceType] | None
    ignore_names: _tt.Names[_tt.NameType] | None
    override_function: _UserOverrideFunction[_tt.NameType, _tt.SourceType, None] | None
    max_fails: float
    reverse: bool
    fmt: _ot.FormatType | None


class AllTranslateParams(TranslateParams[_tt.NameType, _tt.SourceType, _tt.IdType], total=False):
    """All arguments of :meth:`.Translator.translate`."""

    translatable: _t.Required[_tt.Translatable[_tt.NameType, _tt.IdType]]
    copy: bool


class FetchParams(_t.TypedDict, _t.Generic[_tt.NameType, _tt.SourceType, _tt.IdType], total=False):
    """All arguments of :meth:`.Translator.fetch` and :meth:`.Translator.go_offline`."""

    translatable: _tt.Translatable[_tt.NameType, _tt.IdType] | None
    names: _tt.NameTypes[_tt.NameType] | _tt.NameToSource[_tt.NameType, _tt.SourceType] | None
    ignore_names: _tt.Names[_tt.NameType] | None
    override_function: _UserOverrideFunction[_tt.NameType, _tt.SourceType, None] | None
    fmt: _ot.FormatType | None


CacheMissReasonType = _t.Literal["metadata-missing", "metadata-changed", "too-old"]
"""High-level reason why a cached ``Translator`` was rejected."""
