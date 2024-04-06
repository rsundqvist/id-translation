import logging
import warnings
from collections.abc import Iterable
from copy import deepcopy
from datetime import timedelta
from os import getenv
from pathlib import Path
from time import perf_counter
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Literal,
    NoReturn,
    Self,
    Union,
    Unpack,
    overload,
)

import pandas
from rics._internal_support.types import PathLikeType
from rics.collections.dicts import InheritedKeysDict, MakeType
from rics.collections.misc import as_list
from rics.misc import get_public_module, tname
from rics.performance import format_perf_counter

from ._tasks import MappingTask, TranslationTask, generate_task_id
from .exceptions import ConnectionStatusError, TranslationDisabledWarning
from .factory import TranslatorFactory
from .fetching import Fetcher
from .fetching.types import IdsToFetch
from .mapping import Mapper
from .mapping.exceptions import MappingError
from .mapping.types import UserOverrideFunction
from .offline import Format, TranslationMap
from .offline.types import (
    FormatType,
    PlaceholderTranslations,
    SourcePlaceholderTranslations,
)
from .transform.types import Transformers
from .translator_typing import CopyParams, FetcherTypes
from .types import (
    ID,
    CopyTranslatable,
    DictToId,
    DictToList,
    DictToOneTuple,
    DictToSet,
    DictToThreeTuple,
    DictToTwoTuple,
    DictToVarTuple,
    HasSources,
    IdType,
    IdTypes,
    InplaceTranslatable,
    Names,
    NameToSource,
    NameType,
    NameTypes,
    SourceType,
    Translatable,
)
from .utils import ConfigMetadata

LOGGER = logging.getLogger(__package__).getChild("Translator")


ID_TRANSLATION_DISABLED: Literal["ID_TRANSLATION_DISABLED"] = "ID_TRANSLATION_DISABLED"

if TYPE_CHECKING:
    from uuid import UUID

    ID_TRANSLATION_PANDAS_IS_TYPED: bool = False


class Translator(Generic[NameType, SourceType, IdType], HasSources[SourceType]):
    """End-user interface for all translation tasks.

    See :meth:`.Translator.translate` for runtime configuration options. Any argument chosen when the ``Translator`` is
    created can be overridden with :meth:`.Translator.copy`. Use :meth:`.go_offline` to store translations in memory.

    Args:
        fetcher: A :class:`.Fetcher` or ready-to-use translations.
        fmt: String :class:`.Format` specification for translations.
        mapper: A :class:`~.mapping.Mapper` instance for binding names to sources.
        default_fmt: Alternative :class:`.Format` to use fallback translation of unknown IDs.
        default_fmt_placeholders: Shared and/or source-specific default placeholder values for unknown IDs. See
            :meth:`rics.collections.dicts.InheritedKeysDict.make` for details. Sources that are translated using default
            placeholders count as successful translations when using
            :meth:`Translator.translate(maximal_untranslated_fraction != 1) <.Translator.translate>`.
        enable_uuid_heuristics: Enabling may improve matching when :py:class:`~uuid.UUID`-like IDs are in use.
        transformers: A dict ``{source: transformer}`` of initialized :class:`.Transformer` instances.

    Examples:
        Basic usage. For a more complete use case, see the :ref:`dvdrental` example.

        Assume that we have data for people and animals as in the tables below::

            people:            animals:
                 id | name        id | name   | is_nice
              ------+---------   ----+--------+---------
               1991 | Richard      0 | Tarzan | false
               1999 | Sofia        1 | Morris | true
               1904 | Fred         2 | Simba  | true

        In most real cases we'd fetch this table from somewhere. In this case, however, there's so little data that we
        can simply enumerate the components needed for translation ourselves.

        >>> from id_translation import Translator
        >>> translation_data = {
        ...     "animals": {
        ...         "id": [0, 1, 2],
        ...         "name": ["Tarzan", "Morris", "Simba"],
        ...         "is_nice": [False, True, True],
        ...     },
        ...     "people": {1999: "Sofia", 1991: "Richard", 1904: "Fred"},
        ... }
        >>> translator = Translator(translation_data, fmt="{id}:{name}[, nice={is_nice}]")

        Since `people` only has columns `id` and `name`, we can use the simplified ``{id: name}`` data format. We're
        using the full format for `animals` since we have an additional `is_nice` column in this table.

        We didn't define a :class:`.Mapper`, so the names must match exactly.

        >>> data = {"animals": [0, 2], "people": [1991, 1999]}
        >>> translated_data = translator.translate(data)

        The ``Translator`` returns a copy by default. Let's look at the translated data.

        >>> for source, translations in translated_data.items():
        >>>     print(f'Translations for {source=}:')
        >>>     for translated_id in translations:
        >>>         print(f'    {repr(translated_id)}')
        Translations for source='animals':
            '0:Tarzan, nice=False'
            '2:Simba, nice=True'
        Translations for source='people':
            '1991:Richard'
            '1999:Sofia'

        Check out the :ref:`translation-primer` to learn how this is done "under the hood".
    """

    def __init__(
        self,
        fetcher: FetcherTypes[NameType, SourceType, IdType] | None = None,
        fmt: FormatType = Format.DEFAULT,
        mapper: Mapper[NameType, SourceType, None] = None,
        default_fmt: FormatType = Format.DEFAULT_FAILED,
        default_fmt_placeholders: MakeType[SourceType, str, Any] | None = None,
        enable_uuid_heuristics: bool = False,
        transformers: Transformers[SourceType, IdType] | None = None,
    ) -> None:
        self._transformers = {} if transformers is None else transformers

        self._fmt = fmt if isinstance(fmt, Format) else Format(fmt)
        self._default_fmt_placeholders: InheritedKeysDict[SourceType, str, Any] | None
        self._default_fmt_placeholders, self._default_fmt = _handle_default(default_fmt, default_fmt_placeholders)
        self._enable_uuid_heuristics = enable_uuid_heuristics

        self._cached_tmap: TranslationMap[NameType, SourceType, IdType] = self._to_translation_map({})
        self._fetcher: Fetcher[SourceType, IdType]
        if fetcher is None:
            from .testing import TestFetcher, TestMapper

            self._fetcher = TestFetcher([])  # No explicit sources
            if mapper:  # pragma: no cover
                warnings.warn(
                    f"Mapper instance {mapper} given; consider creating a TestFetcher([sources..])-instance manually.",
                    UserWarning,
                    stacklevel=2,
                )
            else:
                mapper = TestMapper()
            warnings.warn(
                "No fetcher given. Translation data will be automatically generated.",
                UserWarning,
                stacklevel=2,
            )
        elif isinstance(fetcher, Fetcher):
            self._fetcher = fetcher
        elif isinstance(fetcher, dict):
            self._cached_tmap = self._to_translation_map(
                {source: PlaceholderTranslations.make(source, pht) for source, pht in fetcher.items()}
            )
        elif isinstance(fetcher, TranslationMap):
            tmap = fetcher.copy()
            tmap.fmt = self._fmt
            tmap.default_fmt = self._default_fmt
            tmap.default_fmt_placeholders = self._default_fmt_placeholders
            self._cached_tmap = tmap
        else:
            raise TypeError(type(fetcher))  # pragma: no cover

        self._mapper: Mapper[NameType, SourceType, None] = mapper or Mapper()
        self._mapper.logger = logging.getLogger(__package__).getChild("mapping").getChild("name-to-source")

        self._config_metadata: ConfigMetadata | None = None
        self._translated_names: NameToSource[NameType, SourceType] | None = None

    @classmethod
    def from_config(
        cls,
        path: PathLikeType,
        extra_fetchers: Iterable[PathLikeType] = (),
    ) -> Self:
        """Create a :class:`.Translator` from TOML inputs.

        Args:
            path: Path to the main TOML configuration file.
            extra_fetchers: Paths to fetching configuration TOML files. If multiple fetchers are defined, they are
                ranked by input order. If a fetcher defined in the main configuration, it will be prioritized (rank=0).

        Returns:
            A new :class:`.Translator` instance with a :attr:`config_metadata` attribute.
        """
        return TranslatorFactory(path, extra_fetchers, cls).create()  # type: ignore[return-value]

    @property
    def config_metadata(self) -> ConfigMetadata:
        """Return :func:`~Translator.from_config` initialization :class:`metadata <.ConfigMetadata>`."""
        if self._config_metadata is None:
            raise ValueError("Not created using Translator.from_config()")  # pragma: no cover
        return self._config_metadata

    def copy(self, **overrides: Unpack[CopyParams[NameType, SourceType, IdType]]) -> Self:
        """Make a copy of this :class:`.Translator`.

        Args:
            overrides: Keyword arguments to use when instantiating the copy. Options that aren't given will be taken
                from the current instance. See the :class:`Translator` class documentation for possible choices.

        Returns:
            A copy of this :class:`.Translator` with `overrides` applied.
        """
        kwargs: dict[str, Any] = {
            "fmt": self.fmt,
            "default_fmt": self.default_fmt,
            "enable_uuid_heuristics": self.enable_uuid_heuristics,
            **overrides,
        }

        if "mapper" not in kwargs:  # pragma: no cover
            kwargs["mapper"] = self.mapper.copy()
        if "default_fmt_placeholders" not in kwargs:
            kwargs["default_fmt_placeholders"] = self._default_fmt_placeholders
        if "fetcher" not in kwargs:
            fetcher: Fetcher[SourceType, IdType] | TranslationMap[NameType, SourceType, IdType]
            if self.online:
                fetcher = self.fetcher
                try:
                    fetcher = deepcopy(fetcher)
                except TypeError as e:
                    msg = (
                        f"Failed to clone fetcher (TypeError: {e}). Caller instance will be reused."
                        "\nTo suppress this warning: Translator.copy(fetcher=Translator.fetcher)"
                    )
                    warnings.warn(msg, category=UserWarning, stacklevel=2)
            else:
                fetcher = self._cached_tmap.copy()
            kwargs["fetcher"] = fetcher

        return type(self)(**kwargs)

    if TYPE_CHECKING:

        @overload
        def translate(
            self,
            translatable: InplaceTranslatable[NameType, IdType],
            names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
            *,
            # https://github.com/python/mypy/issues/7333#issuecomment-788255229
            inplace: Literal[True],
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            maximal_untranslated_fraction: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
        ) -> None: ...

        @overload
        def translate(
            self,
            translatable: CopyTranslatable[IdType],
            names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
            *,
            # https://github.com/python/mypy/issues/7333#issuecomment-788255229
            inplace: Literal[True],
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            maximal_untranslated_fraction: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
        ) -> NoReturn: ...

        @overload
        def translate(
            self,
            translatable: IdTypes,
            names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
            *,
            inplace: Literal[False] = False,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            maximal_untranslated_fraction: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
        ) -> str: ...

        @overload
        def translate(
            self,
            translatable: list[IdType],
            names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
            *,
            inplace: Literal[False] = False,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            maximal_untranslated_fraction: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
        ) -> list[str]: ...

        # This doesn't seem to work; nested generic type issue?
        # TODO Need Higher-Kinded TypeVars?
        # @overload
        # def translate(
        #     self,
        #     translatable: List[List[IdType]],
        #     names: Union[NameTypes[NameType], NameToSource[NameType, SourceType]] = None,
        #     *,
        #     inplace: Literal[False] = False,
        #     ignore_names: Names[NameType] | None = None,
        #     override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
        #     maximal_untranslated_fraction: float = 1.0,
        #     # Translation specification
        #     reverse: bool = False,
        #     fmt: FormatType | None = None,
        # ) -> List[List[str]]:
        #     ...

        @overload
        def translate(
            self,
            translatable: set[IdType],
            names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
            *,
            inplace: Literal[False] = False,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            maximal_untranslated_fraction: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
        ) -> set[str]: ...

        @overload
        def translate(
            self,
            # This is not correct, but using the TypeVar (which the user may bind to get proper typing) doesn't work
            # at this time (python 3.11.3, mypy 1.5.1). Higher-Kinded TypeVars might solve this.
            # TODO: Higher-Kinded TypeVars
            translatable: DictToId[NameType, int] | DictToId[NameType, str] | DictToId[NameType, UUID],
            names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
            *,
            inplace: Literal[False] = False,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            maximal_untranslated_fraction: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
        ) -> DictToId[NameType, str]: ...

        @overload
        def translate(
            self,
            translatable: DictToSet[NameType, IdType],
            names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
            *,
            inplace: Literal[False] = False,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            maximal_untranslated_fraction: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
        ) -> DictToSet[NameType, str]: ...

        @overload
        def translate(
            self,
            translatable: DictToList[NameType, IdType],
            names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
            *,
            inplace: Literal[False] = False,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            maximal_untranslated_fraction: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
        ) -> DictToList[NameType, str]: ...

        @overload
        def translate(  # type: ignore[overload-overlap]  # Overlaps with DictToVarTuple
            self,
            translatable: DictToOneTuple[NameType, IdType],
            names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
            *,
            inplace: Literal[False] = False,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            maximal_untranslated_fraction: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
        ) -> DictToOneTuple[NameType, str]: ...

        @overload
        def translate(  # type: ignore[overload-overlap]  # Overlaps with DictToVarTuple
            self,
            translatable: DictToTwoTuple[NameType, IdType],
            names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
            *,
            inplace: Literal[False] = False,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            maximal_untranslated_fraction: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
        ) -> DictToTwoTuple[NameType, str]: ...

        @overload
        def translate(  # type: ignore[overload-overlap]  # Overlaps with DictToVarTuple
            self,
            translatable: DictToThreeTuple[NameType, IdType],
            names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
            *,
            inplace: Literal[False] = False,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            maximal_untranslated_fraction: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
        ) -> DictToThreeTuple[NameType, str]: ...

        @overload
        def translate(
            self,
            translatable: DictToVarTuple[NameType, IdType],
            names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
            *,
            inplace: Literal[False] = False,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            maximal_untranslated_fraction: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
        ) -> DictToVarTuple[NameType, str]: ...

        @overload
        def translate(
            self,
            translatable: tuple[IdType],
            names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
            *,
            inplace: Literal[False] = False,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            maximal_untranslated_fraction: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
        ) -> tuple[str]: ...

        @overload
        def translate(
            self,
            translatable: tuple[IdType, IdType],
            names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
            *,
            inplace: Literal[False] = False,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            maximal_untranslated_fraction: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
        ) -> tuple[str, str]: ...

        @overload
        def translate(
            self,
            translatable: tuple[IdType, IdType, IdType],
            names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
            *,
            inplace: Literal[False] = False,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            maximal_untranslated_fraction: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
        ) -> tuple[str, str, str]: ...

        @overload
        def translate(
            self,
            translatable: tuple[IdType, ...],
            names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
            *,
            inplace: Literal[False] = False,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            maximal_untranslated_fraction: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
        ) -> tuple[str, ...]: ...

        if ID_TRANSLATION_PANDAS_IS_TYPED:
            # pandas-stubs or similar

            @overload
            def translate(
                self,
                translatable: "pandas.DataFrame",
                names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
                *,
                inplace: Literal[False] = False,
                ignore_names: Names[NameType] | None = None,
                override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
                maximal_untranslated_fraction: float = 1.0,
                # Translation specification
                reverse: bool = False,
                fmt: FormatType | None = None,
            ) -> "pandas.DataFrame": ...

            @overload
            def translate(
                self,
                translatable: "pandas.Series[Any]",
                names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
                *,
                inplace: Literal[False] = False,
                ignore_names: Names[NameType] | None = None,
                override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
                maximal_untranslated_fraction: float = 1.0,
                # Translation specification
                reverse: bool = False,
                fmt: FormatType | None = None,
            ) -> "pandas.Series[str]": ...

            @overload
            def translate(
                self,
                translatable: "pandas.Index[Any]",
                names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
                *,
                inplace: Literal[False] = False,
                ignore_names: Names[NameType] | None = None,
                override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
                maximal_untranslated_fraction: float = 1.0,
                # Translation specification
                reverse: bool = False,
                fmt: FormatType | None = None,
            ) -> "pandas.Index[str]": ...

            @overload
            def translate(
                self,
                translatable: Union["pandas.DataFrame", "pandas.Series[Any]"],
                names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
                *,
                inplace: Literal[True],
                ignore_names: Names[NameType] | None = None,
                override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
                maximal_untranslated_fraction: float = 1.0,
                # Translation specification
                reverse: bool = False,
                fmt: FormatType | None = None,
            ) -> None: ...

            @overload
            def translate(
                self,
                translatable: "pandas.Index[Any]",
                names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
                *,
                # https://github.com/python/mypy/issues/7333#issuecomment-788255229
                inplace: Literal[True],
                ignore_names: Names[NameType] | None = None,
                override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
                maximal_untranslated_fraction: float = 1.0,
                # Translation specification
                reverse: bool = False,
                fmt: FormatType | None = None,
            ) -> NoReturn: ...

        @overload
        def translate(
            self,
            translatable: Translatable[NameType, IdType],
            names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
            *,
            ignore_names: Names[NameType] | None = None,
            inplace: Literal[False] = False,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            maximal_untranslated_fraction: float = 1.0,
            reverse: Literal[False] = False,
            fmt: FormatType | None = None,
        ) -> Translatable[NameType, str]: ...

        @overload
        def translate(
            self,
            translatable: Translatable[NameType, str],
            names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
            *,
            ignore_names: Names[NameType] | None = None,
            inplace: Literal[False] = False,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            maximal_untranslated_fraction: float = 1.0,
            reverse: Literal[True] = True,
            fmt: FormatType | None = None,
        ) -> Translatable[NameType, IdType]: ...

    def translate(
        self,
        translatable: Translatable[NameType, IdType],
        names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
        *,
        ignore_names: Names[NameType] | None = None,
        inplace: bool = False,
        override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
        maximal_untranslated_fraction: float = 1.0,
        reverse: bool = False,
        fmt: FormatType | None = None,
    ) -> Translatable[NameType, str] | None:
        """Translate IDs to human-readable strings.

        Simplified process:
            1. The :attr:`map` method performs name-to-source mapping (see :class:`~.DirectionalMapping`).
            2. The :attr:`fetch` method extracts IDs to translate and retrieves data (see :class:`.TranslationMap`).
            3. Finally, the :attr:`translate` method applies the translations and returns to the caller.

        See the :ref:`translation-primer` page for a detailed process description.

        See Also:
            🔑 This is a key event method. Exit-events are emitted on the ``ℹ️INFO``-level if the :class:`.Translator` is
            :attr:`.online`. Enter-events are always emitted on the ``🪲DEBUG``-level. See :ref:`key-events` for details.

        Args:
            translatable: A data structure to translate.
            names: Explicit names to translate. Derive from `translatable` if ``None``. Alternatively, you may pass a
                ``dict`` on the form ``{name_in_translatable: source_to_use}``.
            ignore_names: Names **not** to translate, or a predicate ``(NameType) -> bool``.
            inplace: If ``True``, translate in-place and return ``None``.
            override_function: A callable ``(name, sources, ids) -> Source | None``. See :meth:`.Mapper.apply`
                for details.
            maximal_untranslated_fraction: The maximum fraction of IDs for which translation may fail. 1=disabled.
            reverse: If ``True``, perform translations back to IDs. Offline mode only.
            fmt: A :class:`format string <.Format>` such as **'{id}:{name}'** use. Default is :attr:`.Translator.fmt`.

        Returns:
            A translated copy of `translatable` if ``inplace=False``, otherwise ``None``.

        Examples:
            Manual `name-to-source <../documentation/translation-primer.html#name-to-source-mapping>`__ mapping with a
            temporary name-only :class:`.Format`.

            ..
               # Hidden setup code
               >>> translator = Translator({"animals": {"id": [2], "name": ["Simba"]}})

            >>> n2s = {"lions": "animals", "big_cats": "animals"}
            >>> translator.translate({"lions": 2, "big_cats": 2}, names=n2s, fmt="{name}")
            {'lions': 'Simba', 'big_cats': 'Simba'}

            Name mappings must be complete; any name not present in the keys will be ignored (left as-is).

        Raises:
            UntranslatableTypeError: If ``type(translatable)`` cannot be translated.
            MissingNamesError: If `names` are not given and cannot be derived from `translatable`.
            MappingError: If any required (explicitly given) names fail to map to a source.
            MappingError: If name-to-source mapping is ambiguous.
            ValueError: If `maximal_untranslated_fraction` is not a valid fraction.
            TooManyFailedTranslationsError: If translation fails for more than `maximal_untranslated_fraction` of IDs.
            ConnectionStatusError: If ``reverse=True`` while the :class:`.Translator` is online.
            UserMappingError: If `override_function` returns a source which is not known, and
                ``self.mapper.unknown_user_override_action != 'ignore'``.
        """
        if getenv(ID_TRANSLATION_DISABLED, "").lower() == "true":
            message = "Translation aborted; ID_TRANSLATION_DISABLED is set."
            LOGGER.warning(message)
            warnings.warn(message, category=TranslationDisabledWarning, stacklevel=2)
            # Return unchanged; this is technically against the API spec.
            return None if inplace else translatable

        if self.online and reverse:  # pragma: no cover
            raise ConnectionStatusError("Reverse translation cannot be performed online.")

        task: TranslationTask[NameType, SourceType, IdType] = TranslationTask(
            self,
            translatable,
            self._fmt if fmt is None else Format.parse(fmt),
            names,
            ignore_names=ignore_names,
            override_function=override_function,
            inplace=inplace,
            maximal_untranslated_fraction=maximal_untranslated_fraction,
            reverse=reverse,
            enable_uuid_heuristics=self._enable_uuid_heuristics,
        )
        task.log_key_event_enter()

        translation_map = self._get_updated_tmap(task)
        if not translation_map:
            # Return unchanged; this is technically against the API spec. If the user has required translation to
            # success through configuration, exceptions will be raised elsewhere. I don't know how to express this using
            # the Python type system.
            return None if inplace else translatable

        task.verify(translation_map)

        ans: Translatable[NameType, str] | None = task.insert(translation_map)

        self._translated_names = dict(task.name_to_source)
        task.log_key_event_exit()
        return ans

    @overload
    def translated_names(self, with_source: Literal[True]) -> NameToSource[NameType, SourceType]: ...

    @overload
    def translated_names(self, with_source: Literal[False] = False) -> list[NameType]: ...

    def translated_names(
        self,
        with_source: bool | Literal[True] | Literal[False] = False,  # https://github.com/python/mypy/issues/14764
    ) -> NameToSource[NameType, SourceType] | list[NameType]:
        """Return the names that were translated by the most recent :meth:`.translate`-call.

        Args:
            with_source: If ``True``, return a dict ``{name: source}`` instead of a list.

        Returns:
            Recent names translated by this :class:`.Translator`, in **arbitrary** order.

        Raises:
            ValueError: If no names have been translated using this :class:`.Translator`.
        """
        if self._translated_names is None:
            raise ValueError("No names have been translated using this Translator.")
        return dict(self._translated_names) if with_source else list(self._translated_names)

    def map(
        self,
        translatable: Translatable[NameType, IdType],
        names: NameTypes[NameType] | None = None,
        *,
        ignore_names: Names[NameType] | None = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
    ) -> NameToSource[NameType, SourceType]:
        """Map names to translation sources.

        Args:
            translatable: A data structure to map names for.
            names: Explicit names to translate. Derive from `translatable` if ``None``.
            ignore_names: Names **not** to translate, or a predicate ``(NameType) -> bool``.
            override_function: A callable ``(name, sources, ids) -> Source | None``. See
                :meth:`Mapper.apply <.mapping.Mapper.apply>` for details.

        Returns:
            A mapping of names to translation sources. Returns ``None`` if mapping failed.

        Raises:
            MissingNamesError: If `names` are not given and cannot be derived from `translatable`.
            MappingError: If any required (explicitly given) names fail to map to a source.
            MappingError: If name-to-source mapping is ambiguous.
            UserMappingError: If `override_function` returns a source which is not known, and
                ``self.mapper.unknown_user_override_action != 'ignore'``.

        See Also:
            🔑 This is a key event method. See :ref:`key-events` for details.
        """
        return MappingTask(
            self,
            translatable,
            names,
            ignore_names=ignore_names,
            override_function=override_function,
        ).name_to_source

    def map_scores(
        self,
        translatable: Translatable[NameType, IdType],
        names: NameTypes[NameType] | None = None,
        *,
        ignore_names: Names[NameType] | None = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
    ) -> "pandas.DataFrame":
        """Returns raw match scores for name-to-source mapping. See :meth:`map` for details."""
        return MappingTask(
            self,
            translatable,
            names,
            ignore_names=ignore_names,
            override_function=override_function,
        ).compute_scores()

    @property
    def sources(self) -> list[SourceType]:
        """A list of known sources names.

        Sources are determines either by the :attr:`.fetcher` or the :attr:`.cache`.
        """
        return list(self.placeholders)

    @property
    def placeholders(self) -> dict[SourceType, list[str]]:
        """A dict ``source: [placeholders..]}``.

        Placeholders shown here are the names as they appear **in the source**.
        """
        return self._fetcher.placeholders if self.online else self._cached_tmap.placeholders

    @property
    def fmt(self) -> Format:
        """Main translation :class:`.Format` for this ``Translator`` instance."""
        return self._fmt

    @property
    def default_fmt(self) -> Format | None:
        """Alternative translation :class:`.Format`, used for unknown IDs."""
        return self._default_fmt

    @property
    def enable_uuid_heuristics(self) -> bool:
        """Enabling may improve matching when :py:class:`~uuid.UUID`-like IDs are in use."""
        return self._enable_uuid_heuristics

    @property
    def online(self) -> bool:
        """Return connectivity status. If ``False``, no new translations may be fetched."""
        return hasattr(self, "_fetcher")

    @property
    def fetcher(self) -> Fetcher[SourceType, IdType]:
        """Return the :class:`.Fetcher` instance used to retrieve translations."""
        if not self.online:
            raise ConnectionStatusError(
                "Cannot fetch new translations.\nHint: Use the Translator.cache-property to access the data."
            )

        return self._fetcher

    @property
    def mapper(self) -> Mapper[NameType, SourceType, None]:
        """Return the :class:`.Mapper` instance used for name-to-source binding."""
        return self._mapper

    @property
    def cache(self) -> TranslationMap[NameType, SourceType, IdType]:
        """Return a :class:`.TranslationMap` of cached translations."""
        return self._cached_tmap

    @classmethod
    def load_persistent_instance(
        cls,
        cache_dir: PathLikeType,
        config_path: PathLikeType,
        extra_fetchers: Iterable[PathLikeType] = (),
        max_age: str | pandas.Timedelta | timedelta = "12h",
    ) -> Self:
        """Load or create a persistent :attr:`~.Fetcher.fetch_all`-instance.

        Instances are created, stored and loaded as determined by a metadata file located in the given `cache_dir`. A
        new :class:`.Translator` will be created if:

        * There is no `'metadata'` file, or
        * the original :class:`.Translator` is too old (see `max_age`), or
        * the current configuration -- as defined by ``(config_path, extra_fetchers, clazz)`` -- has changed in such a
          way that it is no longer equivalent configuration used to create the original :class:`.Translator`. For details, see
          :class:`~.utils.ConfigMetadata`.

        .. warning:: This method is **not** thread safe.

        Args:
            cache_dir: Root directory where the cached translator and associated metadata is stored.
            config_path: Path to the main TOML configuration file.
            extra_fetchers: Paths to fetching configuration TOML files. If multiple fetchers are defined, they are
                ranked by input order. If a fetcher defined in the main configuration, it will be prioritized (rank=0).
            max_age: The maximum age of the cached :class:`.Translator` before it must be recreated. Pass ``max_age='0d'`` to
                force recreation.

        Returns:
            A new or cached :class:`.Translator` instance with a :attr:`config_metadata` attribute.

        See Also:
             The :meth:`from_config` method, which will read the `config_path`.
        """
        path = Path(str(config_path))
        cache_dir = Path(str(cache_dir)).expanduser().absolute()
        cache_dir.mkdir(parents=True, exist_ok=True)

        metadata_path = cache_dir.joinpath("metadata.json")
        cache_path = cache_dir.joinpath("translator.pkl")

        extra_fetcher_paths: list[str] = list(map(str, extra_fetchers))

        metadata = ConfigMetadata.from_toml_paths(
            str(path),
            extra_fetcher_paths,
            clazz=cls,
        )
        use_cached, reason = metadata.use_cached(metadata_path, pandas.Timedelta(max_age).to_pytimedelta())
        if use_cached:
            LOGGER.info(f"Reuse existing Translator; {reason}. Cache dir: '{cache_dir}'.")
            return cls.restore(cache_path)

        LOGGER.info(f"Create new Translator; {reason}. Cache dir: '{cache_dir}'.")
        translator = cls.from_config(path, extra_fetcher_paths)
        translator.go_offline(path=cache_path)
        metadata_path.write_text(translator.config_metadata.to_json())
        return translator

    @classmethod
    def restore(cls, path: PathLikeType) -> Self:
        """Restore a serialized :class:`.Translator`.

        Args:
            path: Path to a serialized :class:`.Translator`.

        Returns:
            A :class:`.Translator`.

        Raises:
            TypeError: If the object at `path` is not a :class:`.Translator` or a subtype thereof.

        See Also:
            The :meth:`go_offline` method.
        """
        import pickle

        full_path = Path(str(path)).expanduser()
        with full_path.open("rb") as f:
            ans = pickle.load(f)  # noqa: S301

        if not isinstance(ans, cls):  # pragma: no cover
            raise TypeError(f"Serialized object at at '{full_path}' is a {type(ans)}, not {cls}.")

        if LOGGER.isEnabledFor(logging.DEBUG):
            extra = "" if ans._config_metadata is None else f" with {ans.config_metadata}"
            LOGGER.debug(f"Deserialized {ans}{extra}.")

        return ans

    def go_offline(
        self,
        translatable: Translatable[NameType, IdType] | None = None,
        names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
        *,
        ignore_names: Names[NameType] | None = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
        maximal_untranslated_fraction: float = 1.0,
        fmt: FormatType | None = None,
        path: PathLikeType = None,
    ) -> Self:
        """Retrieve and store translations in memory.

        .. warning::

           The translator will be disconnected. No new translations may be fetched after this method returns.

        Args:
            translatable: Data from which IDs to fetch will be extracted. Fetch all IDs if ``None``.
            names: Explicit names to translate. Derive from `translatable` if ``None``.
            ignore_names: Names **not** to translate, or a predicate ``(NameType) -> bool``.
            override_function: A callable ``(name, sources, ids) -> Source | None``. See :meth:`.Mapper.apply`
                for details.
            maximal_untranslated_fraction: The maximum fraction of IDs for which translation may fail. 1=disabled.
            fmt: A :class:`format string <.Format>` such as **'{id}:{name}'** use. Default is :attr:`.Translator.fmt`.
            path: If given, serialize the :class:`.Translator` to disk after retrieving data.

        Returns:
            Self, for chained assignment.

        Raises:
            ForbiddenOperationError: If :meth:`.Fetcher.fetch_all` is disabled and ``translatable=None``.
            MappingError: If :meth:`map` fails (only when `translatable` is given).

        Notes:
            The :class:`.Translator` is guaranteed to be :func:`~rics.misc.serializable` once offline. Fetchers often
            aren't as they require things like database connections to function.

        See Also:
            The :meth:`restore` method.
        """
        start = perf_counter()
        translation_map = self._user_fetch(
            translatable,
            names,
            ignore_names=ignore_names,
            override_function=override_function,
            maximal_untranslated_fraction=maximal_untranslated_fraction,
            fmt=fmt,
        )
        self.fetcher.close()
        del self._fetcher
        self._cached_tmap = translation_map

        LOGGER.info(f"Created {translation_map} in {format_perf_counter(start)}.")
        if path:
            import pickle

            path = Path(str(path)).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as f:
                pickle.dump(self, f)

            cls = type(self)
            pretty = get_public_module(cls, resolve_reexport=True) + "." + tname(self, prefix_classname=True)
            LOGGER.info(f"Serialized {pretty!r} of size {path.stat().st_size / 2**20:.2g} MiB at path='{path}'.")

        return self

    def fetch(
        self,
        translatable: Translatable[NameType, IdType] | None = None,
        names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
        *,
        ignore_names: Names[NameType] | None = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
        maximal_untranslated_fraction: float = 1.0,
        fmt: FormatType | None = None,
    ) -> TranslationMap[NameType, SourceType, IdType]:
        """Fetch translations.

        Calling ``fetch`` without arguments will perform a :meth:`.Fetcher.fetch_all` -operation, without going offline.

        The returned :class:`.TranslationMap` may be converted to native types with :meth:`.TranslationMap.to_dicts`.

        Args:
            translatable: A data structure to translate.
            names: Explicit names to translate. Derive from `translatable` if ``None``. Alternatively, you may pass a
                ``dict`` on the form ``{name_in_translatable: source_to_use}``.
            ignore_names: Names **not** to translate, or a predicate ``(NameType) -> bool``.
            override_function: A callable ``(name, sources, ids) -> Source | None``. See :meth:`.Mapper.apply`
                for details.
            maximal_untranslated_fraction: The maximum fraction of IDs for which translation may fail. 1=disabled.
            fmt: A :class:`format string <.Format>` such as **'{id}:{name}'** use. Default is :attr:`.Translator.fmt`.

        Returns:
            A :class:`.TranslationMap`.

        Raises:
            ConnectionStatusError: If disconnected from the fetcher, i.e. not :attr:`online`.

        Examples:
            Using the returned :class:`.TranslationMap` class.

            ..
               # Hidden setup code
               >>> from .fetching import MemoryFetcher
               >>> translation_data = {
               ...     "animals": {"id": [0, 1, 2], "name": ["Tarzan", "Morris", "Simba"]},
               ...     "people": {"id": [1999, 1991], "name": ["Sofia", "Richard"]},
               ... }
               >>> translator = Translator(MemoryFetcher(translation_data))

            >>> translation_map = translator.fetch()
            >>> translation_map
            TranslationMap('animals': 3 IDs, 'people': 2 IDs)

            **Convert to finished translations.**

            * :meth:`.TranslationMap.to_translations` → ``{source: MagicDict}``, where a :class:`.MagicDict` is similar
              to a regular ``dict[IdType, str]``-type dict.

            >>> people = translation_map.to_translations()["people"]
            >>> people
            {1999: '1999:Sofia', 1991: '1991:Richard'}

            .. warning::

               The :class:`.MagicDict` class is used internally and has a few important differences from the built-in
               type. Please refer to the :class:`.MagicDict` class documentation for details.

            To convert to a :class:`.MagicDict` to a regular ``dict``, simply use the dict constructor:

            >>> dict(people)
            {1999: '1999:Sofia', 1991: '1991:Richard'}

            **Convert to raw translation data.**

            * :meth:`.TranslationMap.to_pandas` → ``{source: DataFrame}``
            * :meth:`.TranslationMap.to_dicts` → ``{source: {placeholder: [values...]}}``

            >>> translation_map.to_dicts()["people"]
            {'id': [1999, 1991], 'name': ['Sofia', 'Richard']}
        """
        return self._user_fetch(
            translatable,
            names,
            ignore_names=ignore_names,
            override_function=override_function,
            maximal_untranslated_fraction=maximal_untranslated_fraction,
            fmt=fmt,
        )

    def _user_fetch(
        self,
        translatable: Translatable[NameType, IdType] | None = None,
        names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
        *,
        ignore_names: Names[NameType] | None = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
        maximal_untranslated_fraction: float = 1.0,
        fmt: FormatType | None = None,
    ) -> TranslationMap[NameType, SourceType, IdType]:
        fmt = self._fmt if fmt is None else Format.parse(fmt)

        if translatable is None:
            translation_map = self._to_translation_map(self._fetch(None), fmt=fmt)

            if names is None:
                pass  # Callers must perform mapping unless name=source.
            elif isinstance(names, dict):
                translation_map.name_to_source = names
            else:
                translation_map.name_to_source = self.mapper.apply(
                    as_list(names),
                    translation_map.sources,
                    override_function=override_function,
                ).flatten()
        else:
            task = TranslationTask(
                self,
                translatable,
                self._fmt,
                names,
                ignore_names=ignore_names,
                maximal_untranslated_fraction=maximal_untranslated_fraction,
                enable_uuid_heuristics=self._enable_uuid_heuristics,
            )
            if not task.name_to_source:
                msg = f"No names in the {tname(translatable, prefix_classname=True)!r}-type data were mapped."
                raise MappingError(msg)

            translation_map = self._get_updated_tmap(task, force_fetch=True)
            if LOGGER.isEnabledFor(logging.DEBUG):
                not_fetched = set(self.fetcher.sources).difference(translation_map.sources)
                LOGGER.debug(f"Available sources {not_fetched} were not fetched.")

            task.verify(translation_map)

        return translation_map

    def _get_updated_tmap(
        self,
        task: TranslationTask[NameType, SourceType, IdType],
        force_fetch: bool = False,
    ) -> TranslationMap[NameType, SourceType, IdType]:
        """Get an updated translation map."""
        name_to_source = task.name_to_source
        if not name_to_source:
            return self._to_translation_map({})  # Nothing to translate.

        translation_map = self._execute_fetch(task) if (force_fetch or not self.cache) else self.cache

        translation_map.enable_uuid_heuristics = task.enable_uuid_heuristics
        translation_map.fmt = task.fmt
        translation_map.name_to_source = task.name_to_source  # Update
        return translation_map

    @property
    def transformers(self) -> Transformers[SourceType, IdType]:
        """Get a dict ``{source: transformer}`` of :class:`.Transformer` instances used by this ``Translator``."""
        return self._transformers

    def _execute_fetch(
        self, task: TranslationTask[NameType, SourceType, IdType]
    ) -> TranslationMap[NameType, SourceType, IdType]:
        source_to_ids = task.extract_ids()

        for source in source_to_ids:
            if (transformer := self._transformers.get(source)) is not None:
                transformer.update_ids(source_to_ids[source])

        ids_to_fetch = [IdsToFetch(source, ids=ids) for source, ids in source_to_ids.items()]
        source_translations = self._fetch(ids_to_fetch, fmt=task.fmt, task_id=task.task_id)
        return self._to_translation_map(source_translations, fmt=task.fmt)

    def _fetch(
        self,
        ids_to_fetch: list[IdsToFetch[SourceType, IdType]] | None,
        fmt: Format = None,
        task_id: int | None = None,
    ) -> SourcePlaceholderTranslations[SourceType]:
        fmt = fmt or self._fmt
        placeholders = fmt.placeholders
        required = fmt.required_placeholders

        if self._default_fmt and ID in self._default_fmt.placeholders and ID not in placeholders:
            # Ensure that default translations can always use the ID
            placeholders = (*placeholders, ID)
            required = (*required, ID)

        if task_id is None:
            task_id = generate_task_id()

        if ids_to_fetch is None:
            return self.fetcher.fetch_all(
                placeholders,
                required=required,
                task_id=task_id,
                enable_uuid_heuristics=self._enable_uuid_heuristics,
            )
        else:
            return self.fetcher.fetch(
                ids_to_fetch,
                placeholders,
                required=required,
                task_id=task_id,
                enable_uuid_heuristics=self._enable_uuid_heuristics,
            )

    def _to_translation_map(
        self,
        source_translations: SourcePlaceholderTranslations[SourceType],
        fmt: Format = None,
    ) -> TranslationMap[NameType, SourceType, IdType]:
        return TranslationMap(
            source_translations,
            fmt=fmt or self._fmt,
            default_fmt=self._default_fmt,
            default_fmt_placeholders=self._default_fmt_placeholders,
            enable_uuid_heuristics=self._enable_uuid_heuristics,
            transformers=self._transformers,
        )

    def __repr__(self) -> str:
        more = f"fetcher={self.fetcher}" if self.online else f"cache={self.cache}"

        online = self.online
        return f"{tname(self)}({online=}: {more})"


def _handle_default(
    default_fmt: FormatType,
    default_fmt_placeholders: MakeType[SourceType, str, Any] | None,
) -> tuple[InheritedKeysDict[SourceType, str, Any], Format]:
    default_fmt = Format.parse(default_fmt)

    if not default_fmt_placeholders:
        return InheritedKeysDict(), default_fmt

    if isinstance(default_fmt_placeholders, InheritedKeysDict):
        default_placeholders = default_fmt_placeholders
    else:
        default_placeholders = InheritedKeysDict.make(default_fmt_placeholders)

    return default_placeholders, default_fmt
