import logging
import pickle
from collections.abc import Iterable, Mapping, Sequence
from contextlib import nullcontext
from copy import deepcopy
from datetime import timedelta
from time import perf_counter
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Literal,
    NoReturn,
    Self,
    Unpack,
    overload,
)

from rics.collections.dicts import InheritedKeysDict, MakeType
from rics.collections.misc import as_list
from rics.env.read import read_bool
from rics.misc import tname
from rics.paths import AnyPath, any_path_to_path
from rics.strings import format_seconds as fmt_sec
from rics.types import LiteralHelper

from . import logging as _logging
from ._tasks import MappingTask, NamesTask, TranslationTask
from ._transformer_registry import TransformerRegistry
from ._utils import add_hints, replace_atomically
from ._utils.emit_warning import emit_warning
from .exceptions import (
    ConfigurationChangedError,
    ConnectionStatusError,
    MissingNamesError,
    NoSourcesError,
    TranslationDisabledWarning,
)
from .fetching import Fetcher, MultiFetcher
from .fetching.types import IdsToFetch
from .mapping import Mapper
from .mapping.matrix import ScoreMatrix
from .mapping.types import UserOverrideFunction
from .offline import Format, TranslationMap
from .offline.types import (
    FormatType,
    PlaceholderTranslations,
    SourcePlaceholderTranslations,
)
from .testing import TestFetcher, TestMapper
from .toml import TranslatorFactory, meta
from .transform.types import OnExistingTransformer, Transformer, TransformersArg
from .translator_typing import CopyParams, FetcherCopyMode, FetcherTypes
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
    ExplicitNames,
    HasSources,
    IdType,
    IdTypes,
    InplaceTranslatable,
    Names,
    NameToSource,
    NameType,
    SourceType,
    Translatable,
)

LOGGER = logging.getLogger(__package__).getChild("Translator")


FETCHER_COPY_MODE_HELPER: LiteralHelper[FetcherCopyMode] = LiteralHelper(
    FetcherCopyMode,
    default_name="fetcher",
    type_name="FetcherCopyMode",
)


ID_TRANSLATION_DISABLED = "ID_TRANSLATION_DISABLED"


if TYPE_CHECKING:
    from uuid import UUID

    import pandas

    ID_TRANSLATION_PANDAS_IS_TYPED: bool = False


class Translator(Generic[NameType, SourceType, IdType], HasSources[SourceType]):
    r"""End-user interface for all translation tasks.

    See :meth:`Translator.translate <id_translation.Translator.translate>` for runtime configuration options. Any
    argument chosen when the ``Translator`` is created, except the `fetcher`, can be overridden with
    :meth:`Translator.copy <id_translation.Translator.copy>`. Use :meth:`~id_translation.Translator.go_offline` to store
    translations in memory.

    Args:
        fetcher: A :class:`~id_translation.fetching.Fetcher`, or translations as inline data.
        fmt: String :class:`~id_translation.offline.Format` specification for translations.
        mapper: A :class:`~id_translation.mapping.Mapper` instance for binding names to sources.
        default_fmt: Alternative :class:`~id_translation.offline.Format` to use for fallback translation of unknown IDs.
        default_fmt_placeholders: Shared and/or source-specific default placeholder values for unknown IDs. See
            :meth:`InheritedKeysDict.make() <rics.collections.dicts.InheritedKeysDict.make>` for details.
        enable_uuid_heuristics: Improves matching when :py:class:`~uuid.UUID`-like IDs are in use.
        transformers: A dict ``{source: transformer}`` of initialized
            :class:`~id_translation.transform.types.Transformer` instances. Values may be a sequence to chain per
            source. Inline data :ref:`settles <transformation-primer-settling>` at construction, so pass its
            transformers here. See the :ref:`transformation-primer` for details.

    .. _translator-docstring-example:
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
        >>> fmt = "{id}:{name}[, nice={is_nice}]"
        >>> translator = Translator(translation_data, fmt=fmt)

        Since `people` only has columns `id` and `name`, we can use the simplified ``{id: name}`` data format. We're
        using the full format for `animals` since we have an additional `is_nice` column in this table. We didn't define
        a :class:`~id_translation.mapping.Mapper`, so the column names must match exactly.

        >>> import pandas as pd
        >>> df = pd.DataFrame({"animals": [0, 2], "people": [1991, 1999]})
        >>> translator.translate(df)  # Returns a copy
                        animals        people
        0  0:Tarzan, nice=False  1991:Richard
        1    2:Simba, nice=True    1999:Sofia

        Check out the :ref:`translation-primer` to learn how this is done "under the hood".
    """

    def __init__(
        self,
        fetcher: FetcherTypes[SourceType, IdType] | None = None,
        *,
        fmt: FormatType = Format.DEFAULT,
        mapper: Mapper[NameType, SourceType, None] | None = None,
        default_fmt: FormatType = Format.DEFAULT_FAILED,
        default_fmt_placeholders: MakeType[SourceType, str, Any] | None = None,
        enable_uuid_heuristics: bool = False,
        transformers: TransformersArg[SourceType, IdType] | None = None,
    ) -> None:
        self._fetcher: Fetcher[SourceType, IdType] | None = None
        self._cached_tmap: TranslationMap[NameType, SourceType, IdType] | None = None

        self._tx: TransformerRegistry[NameType, SourceType, IdType] = TransformerRegistry()
        self._config_metadata: meta.ConfigMetadata | None = None
        for source, transformer in (transformers or {}).items():
            # Not the public method: an override may rely on attributes this constructor has not created yet.
            self._tx.register(source, transformer, on_existing="raise")

        self._fmt = Format.parse(fmt)
        self._default_fmt_placeholders, self._default_fmt = _handle_default(default_fmt, default_fmt_placeholders)
        self._enable_uuid_heuristics = enable_uuid_heuristics

        if fetcher is None:
            self._fetcher = TestFetcher([])  # No explicit sources
            if mapper:  # pragma: no cover
                emit_warning(
                    f"Mapper instance {mapper} given; consider creating a TestFetcher([sources..])-instance manually."
                )
            else:
                mapper = TestMapper()
            emit_warning("No fetcher given. Translation data will be automatically generated.")
        elif isinstance(fetcher, Fetcher):
            self._fetcher = fetcher
        elif isinstance(fetcher, TranslationMap):
            # The map carries its own format, defaults and transformers. So does this constructor. Either side winning
            # silently loses the other's, and a lost transformer can break translation in confusing ways.
            exc = TypeError(f"Cannot create a {tname(self)} from a TranslationMap.")
            exc.add_note(f"Hint: Use {tname(self)}(translation_map.to_dicts(), ...) instead.")
            if sources := list(fetcher.transformers):
                exc.add_note(f"Hint: The map has transformers for sources {sources}; pass `transformers` too.")
            raise exc
        elif isinstance(fetcher, Mapping):
            source_translations = {source: PlaceholderTranslations.make(source, pht) for source, pht in fetcher.items()}
            self._tx.freeze(self, source_translations)
            self._cached_tmap = self._to_translation_map(source_translations)
        else:
            raise TypeError(type(fetcher))  # pragma: no cover

        self._mapper: Mapper[NameType, SourceType, None] = mapper or Mapper()
        self._mapper.logger = LOGGER.getChild("map")

        self._translated_names: tuple[int, NameToSource[NameType, SourceType]] | None = None

    def __setstate__(self, state: Any) -> None:
        # Snapshots are same-version artifacts by definition: `ConfigMetadata` records the `id-translation` version and
        # `use_cached()` refuses any mismatch, so there is no cross-version repair. `load_persistent_instance` rejects a
        # foreign snapshot before reading it, but `restore` is handed a path and cannot, so recognise the shape here
        # rather than unpickle into an instance that fails later with an unrelated AttributeError.
        slots: dict[str, Any] = {}
        if isinstance(state, tuple):  # A subclass with `__slots__`; `object.__getstate__` returns `(dict, slots)`.
            state, slots = state[0] or {}, state[1] or {}

        if "_tx" not in state:
            exc = ValueError("Snapshot was written by an incompatible version of id-translation.")
            exc.add_note(f"Hint: Recreate it with {type(self).__name__}.go_offline(path=...).")
            raise exc

        self.__dict__.update(state)
        for key, value in slots.items():
            setattr(self, key, value)

    @classmethod
    def from_config(
        cls,
        path: AnyPath,
        extra_fetchers: AnyPath | Iterable[AnyPath] = (),
    ) -> Self:
        """Create a :class:`~id_translation.Translator` from TOML inputs.

        See :ref:`translator-config` for help.

        Args:
            path: Path to the main TOML configuration file.
            extra_fetchers: A path, or paths, to fetching configuration TOML files. If multiple fetchers are defined,
                they are ranked by input order. A fetcher defined in the main configuration is prioritized (rank=0).

        Returns:
            A new :class:`~id_translation.Translator` instance with a :attr:`~id_translation.Translator.config_metadata`
            attribute.
        """
        # docs: https://id-translation.readthedocs.io/en/stable/documentation/translator-config.html
        factory = TranslatorFactory(path, extra_fetchers, cls)
        return factory.create()  # type: ignore[return-value]

    @property
    def config_metadata(self) -> meta.ConfigMetadata:
        """Return :func:`~id_translation.Translator.from_config` initialization :class:`metadata <id_translation.toml.meta.ConfigMetadata>`.

        Raises:
            ValueError: If this instance was not created by :meth:`~id_translation.Translator.from_config`, or copied
                from such an instance.
        """
        if self._config_metadata is None:
            raise ValueError("Not created using Translator.from_config()")  # pragma: no cover
        return self._config_metadata

    def initialize_sources(
        self,
        *,
        settle_transformers: bool = True,
        require_sources: bool = True,
        task_id: int | None = None,
    ) -> Self:
        """Perform source discovery (fetcher initialization).

        This method does nothing if the ``Translator`` isn't :attr:`~id_translation.Translator.online`.

        Args:
            settle_transformers: If ``True``, :ref:`settle <transformation-primer-settling>` the
                :attr:`~id_translation.Translator.transformers` as well. Pass ``False`` to register transformers based
                on the discovered :attr:`~id_translation.Translator.sources` first; the next call without it settles
                them, implicit calls included.
            require_sources: If ``False``, accept a fetcher that finds no sources. Passing this to the first call also
                covers implicit calls, and lets :meth:`~id_translation.Translator.go_offline` take an empty snapshot.
            task_id: Used for logging.

        Returns:
            Self, for chained assignment.

        Raises:
            ~id_translation.exceptions.NoSourcesError: If the fetcher finds no sources and `require_sources` is set.

        See Also:
            🧵 Thread safe, unless the fetcher is shared with another instance; see :ref:`thread-safety-fetchers`.
        """
        tx = self._tx
        if self.online and not (tx.discovered and tx.queried):
            # Locked: concurrent first calls must not both discover, nor both chain what the fetcher provides.
            with tx.lock:
                if not tx.discovered:
                    self.fetcher.initialize_sources(_logging.generate_task_id() if task_id is None else task_id)
                    if require_sources:
                        self._check_has_sources()  # Before `discovered`, so that every call checks until one passes.
                    tx.discovered = True
                tx.apply_from_fetcher(self)  # Does nothing once a racing call has queried.

        if settle_transformers and not tx.frozen:
            with tx.lock:
                tx.freeze(self)

        return self

    def _serves_sources(self) -> bool:
        return bool(self.sources) or isinstance(self.fetcher, TestFetcher)  # Reports no sources but serves all.

    def _check_has_sources(self) -> None:
        if self._serves_sources():
            return

        fetcher = self.fetcher
        hints = ["Call initialize_sources(require_sources=False) first if a Translator without sources is expected."]
        if isinstance(fetcher, MultiFetcher) and (unresolved := fetcher._unresolved_children()):
            hints.insert(0, f"Optional fetchers discarded because source discovery raised: {unresolved}.")
        raise NoSourcesError(f"No sources found by {fetcher}.", hints=hints)

    def copy(self, **overrides: Unpack[CopyParams[NameType, SourceType, IdType]]) -> Self:
        """Make a copy of this :class:`~id_translation.Translator`.

        Args:
            transformers: A dict ``{source: transformer}`` that replaces all transformers, without asking the fetcher
                for more. ``None`` starts empty and asks the fetcher on first use, as the constructor does. When
                omitted, the copy keeps this instance's transformers, and is
                :ref:`settled <transformation-primer-settling>` if this instance is.
            overrides: Keyword arguments to use when instantiating the copy. Options that aren't given will be taken
                from the current instance. See the :class:`~id_translation.Translator` class documentation for possible
                choices (except `fetcher`; see Notes).

        Returns:
            A copy of this :class:`~id_translation.Translator` with `overrides` applied.

        Notes:
            User types are copied using :func:`copy.deepcopy`. The data source
            (:attr:`~id_translation.Translator.fetcher` or :attr:`~id_translation.Translator.cache`) is fixed for the
            lifetime of a ``Translator`` and cannot be replaced this way; `fetcher` instead selects how the *current*
            one is carried over: ``'keep'`` reuses it as-is, ``'copy'`` requires a successful :func:`~copy.deepcopy`,
            and the default, ``'auto'``, tries to clone and falls back to ``'keep'`` with a warning if that fails.
            This only applies while :attr:`~id_translation.Translator.online`; an offline copy always shares the
            cached translation records with the original, which are never mutated in place.

            🧵 Not thread safe. See :ref:`thread-safety-copying` for details.
        """
        cls = type(self)
        fetcher_mode = FETCHER_COPY_MODE_HELPER.check(overrides.pop("fetcher", "auto"))

        kwargs: dict[str, Any] = {
            "fmt": self.fmt,
            "default_fmt": self.default_fmt,
            "default_fmt_placeholders": self._default_fmt_placeholders,
            "enable_uuid_heuristics": self.enable_uuid_heuristics,
            **overrides,
        }

        if "mapper" not in kwargs:
            kwargs["mapper"] = self.mapper.copy()

        carry = "transformers" not in kwargs
        if carry:
            kwargs["transformers"] = None  # The whole registry is carried over below.

        tx = self._tx
        lock = nullcontext() if not self.online or (tx.discovered and tx.queried and tx.frozen) else tx.lock
        with lock:  # A first use finishing in between would leave the cloned fetcher and the registry out of step.
            kwargs["fetcher"] = self._copy_fetcher(fetcher_mode)
            registry = tx.copy(self) if carry else None  # `owner` only names the class in a warning: same as the copy.
            discovered = tx.discovered

        new = cls(**kwargs)
        new._config_metadata = self._config_metadata
        if not self.online:
            # The constructor rebuilt the cache from records alone; keep what the snapshot knew, as pickling does.
            cache = new.cache
            cache.name_to_source = self.cache.name_to_source
            if "fmt" not in overrides:
                cache.fmt = self.cache.fmt
        if registry is not None:
            # An offline copy is settled by the constructor, which carrying must not reopen.
            cached = new._cached_tmap
            new._tx = registry
            if cached is not None:
                new._tx.freeze(new, report=False)
                # The constructor built that cache before the registry arrived, so each FormatApplier still has the
                # empty one baked in. Rebind them in place instead of rebuilding the map from scratch.
                cached._set_transformers(new._tx.settled(new))
        else:
            new._tx.inherit(discovered=discovered, complete=kwargs["transformers"] is not None)
        return new

    def __copy__(self) -> Self:
        # Sharing the registry would let either instance settle or register for the other; share only the fetcher.
        return self.copy(fetcher="keep")

    def _copy_fetcher(
        self,
        mode: FetcherCopyMode,
    ) -> Fetcher[SourceType, IdType] | SourcePlaceholderTranslations[SourceType]:
        if not self.online:
            return self.cache._extract_translations()  # Records are never mutated in place, so all modes share them.
        if mode == "keep":
            return self.fetcher

        try:
            return deepcopy(self.fetcher)
        except TypeError as e:
            hint = f"{type(self).__name__}.copy(fetcher='keep')"
            if mode == "copy":
                e.add_note(f"Hint: Could not clone {tname(self.fetcher, include_module=True)}. Use {hint} to reuse it.")
                raise
            emit_warning(
                f"Failed to clone fetcher (TypeError: {e}). Caller instance will be reused."
                f"\nHint: To suppress this warning: {hint}"
            )
            return self.fetcher

    if TYPE_CHECKING:

        @overload
        def translate(
            self,
            translatable: InplaceTranslatable[NameType, IdType],
            names: ExplicitNames[NameType, SourceType] | None = None,
            *,
            # https://github.com/python/mypy/issues/7333#issuecomment-788255229
            copy: Literal[False],
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            max_fails: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
            io_kwargs: Mapping[str, Any] | None = None,
        ) -> None: ...

        @overload
        def translate(
            self,
            translatable: CopyTranslatable[IdType],
            names: ExplicitNames[NameType, SourceType] | None = None,
            *,
            # https://github.com/python/mypy/issues/7333#issuecomment-788255229
            copy: Literal[False],
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            max_fails: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
            io_kwargs: Mapping[str, Any] | None = None,
        ) -> NoReturn: ...

        @overload
        def translate(
            self,
            translatable: IdTypes,
            names: ExplicitNames[NameType, SourceType] | None = None,
            *,
            copy: Literal[True] = True,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            max_fails: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
            io_kwargs: Mapping[str, Any] | None = None,
        ) -> str: ...

        @overload
        def translate(
            self,
            translatable: list[IdType],
            names: ExplicitNames[NameType, SourceType] | None = None,
            *,
            copy: Literal[True] = True,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            max_fails: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
            io_kwargs: Mapping[str, Any] | None = None,
        ) -> list[str]: ...

        @overload
        def translate(
            self,
            translatable: set[IdType],
            names: ExplicitNames[NameType, SourceType] | None = None,
            *,
            copy: Literal[True] = True,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            max_fails: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
            io_kwargs: Mapping[str, Any] | None = None,
        ) -> set[str]: ...

        @overload
        def translate(
            self,
            # This is not correct, but using the TypeVar (which the user may bind to get proper typing) doesn't work
            # at this time (python 3.11.3, mypy 1.5.1). Higher-Kinded TypeVars might solve this.
            # TODO: Higher-Kinded TypeVars
            translatable: DictToId[NameType, int] | DictToId[NameType, str] | DictToId[NameType, UUID],
            names: ExplicitNames[NameType, SourceType] | None = None,
            *,
            copy: Literal[True] = True,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            max_fails: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
            io_kwargs: Mapping[str, Any] | None = None,
        ) -> DictToId[NameType, str]: ...

        @overload
        def translate(
            self,
            translatable: DictToSet[NameType, IdType],
            names: ExplicitNames[NameType, SourceType] | None = None,
            *,
            copy: Literal[True] = True,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            max_fails: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
            io_kwargs: Mapping[str, Any] | None = None,
        ) -> DictToSet[NameType, str]: ...

        @overload
        def translate(
            self,
            translatable: DictToList[NameType, IdType],
            names: ExplicitNames[NameType, SourceType] | None = None,
            *,
            copy: Literal[True] = True,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            max_fails: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
            io_kwargs: Mapping[str, Any] | None = None,
        ) -> DictToList[NameType, str]: ...

        @overload
        def translate(  # Overlaps with DictToVarTuple
            self,
            translatable: DictToOneTuple[NameType, IdType],
            names: ExplicitNames[NameType, SourceType] | None = None,
            *,
            copy: Literal[True] = True,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            max_fails: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
            io_kwargs: Mapping[str, Any] | None = None,
        ) -> DictToOneTuple[NameType, str]: ...

        @overload
        def translate(  # Overlaps with DictToVarTuple
            self,
            translatable: DictToTwoTuple[NameType, IdType],
            names: ExplicitNames[NameType, SourceType] | None = None,
            *,
            copy: Literal[True] = True,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            max_fails: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
            io_kwargs: Mapping[str, Any] | None = None,
        ) -> DictToTwoTuple[NameType, str]: ...

        @overload
        def translate(  # Overlaps with DictToVarTuple
            self,
            translatable: DictToThreeTuple[NameType, IdType],
            names: ExplicitNames[NameType, SourceType] | None = None,
            *,
            copy: Literal[True] = True,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            max_fails: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
            io_kwargs: Mapping[str, Any] | None = None,
        ) -> DictToThreeTuple[NameType, str]: ...

        @overload
        def translate(
            self,
            translatable: DictToVarTuple[NameType, IdType],
            names: ExplicitNames[NameType, SourceType] | None = None,
            *,
            copy: Literal[True] = True,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            max_fails: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
            io_kwargs: Mapping[str, Any] | None = None,
        ) -> DictToVarTuple[NameType, str]: ...

        @overload
        def translate(
            self,
            translatable: tuple[IdType],
            names: ExplicitNames[NameType, SourceType] | None = None,
            *,
            copy: Literal[True] = True,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            max_fails: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
            io_kwargs: Mapping[str, Any] | None = None,
        ) -> tuple[str]: ...

        @overload
        def translate(
            self,
            translatable: tuple[IdType, IdType],
            names: ExplicitNames[NameType, SourceType] | None = None,
            *,
            copy: Literal[True] = True,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            max_fails: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
            io_kwargs: Mapping[str, Any] | None = None,
        ) -> tuple[str, str]: ...

        @overload
        def translate(
            self,
            translatable: tuple[IdType, IdType, IdType],
            names: ExplicitNames[NameType, SourceType] | None = None,
            *,
            copy: Literal[True] = True,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            max_fails: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
            io_kwargs: Mapping[str, Any] | None = None,
        ) -> tuple[str, str, str]: ...

        @overload
        def translate(
            self,
            translatable: tuple[IdType, ...],
            names: ExplicitNames[NameType, SourceType] | None = None,
            *,
            copy: Literal[True] = True,
            ignore_names: Names[NameType] | None = None,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            max_fails: float = 1.0,
            # Translation specification
            reverse: bool = False,
            fmt: FormatType | None = None,
            io_kwargs: Mapping[str, Any] | None = None,
        ) -> tuple[str, ...]: ...

        if ID_TRANSLATION_PANDAS_IS_TYPED:
            # pandas-stubs or similar

            @overload
            def translate(
                self,
                translatable: "pandas.DataFrame",
                names: ExplicitNames[NameType, SourceType] | None = None,
                *,
                copy: Literal[True] = True,
                ignore_names: Names[NameType] | None = None,
                override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
                max_fails: float = 1.0,
                # Translation specification
                reverse: bool = False,
                fmt: FormatType | None = None,
                io_kwargs: Mapping[str, Any] | None = None,
            ) -> "pandas.DataFrame": ...

            @overload
            def translate(
                self,
                translatable: "pandas.Series[Any]",
                names: ExplicitNames[NameType, SourceType] | None = None,
                *,
                copy: Literal[True] = True,
                ignore_names: Names[NameType] | None = None,
                override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
                max_fails: float = 1.0,
                # Translation specification
                reverse: bool = False,
                fmt: FormatType | None = None,
                io_kwargs: Mapping[str, Any] | None = None,
            ) -> "pandas.Series[str]": ...

            @overload
            def translate(
                self,
                translatable: "pandas.Index[Any]",
                names: ExplicitNames[NameType, SourceType] | None = None,
                *,
                copy: Literal[True] = True,
                ignore_names: Names[NameType] | None = None,
                override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
                max_fails: float = 1.0,
                # Translation specification
                reverse: bool = False,
                fmt: FormatType | None = None,
                io_kwargs: Mapping[str, Any] | None = None,
            ) -> "pandas.Index[str]": ...

            @overload
            def translate(
                self,
                translatable: "pandas.DataFrame" | "pandas.Series[Any]",
                names: ExplicitNames[NameType, SourceType] | None = None,
                *,
                copy: Literal[False],
                ignore_names: Names[NameType] | None = None,
                override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
                max_fails: float = 1.0,
                # Translation specification
                reverse: bool = False,
                fmt: FormatType | None = None,
                io_kwargs: Mapping[str, Any] | None = None,
            ) -> None: ...

            @overload
            def translate(
                self,
                translatable: "pandas.Index[Any]",
                names: ExplicitNames[NameType, SourceType] | None = None,
                *,
                # https://github.com/python/mypy/issues/7333#issuecomment-788255229
                copy: Literal[False],
                ignore_names: Names[NameType] | None = None,
                override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
                max_fails: float = 1.0,
                # Translation specification
                reverse: bool = False,
                fmt: FormatType | None = None,
                io_kwargs: Mapping[str, Any] | None = None,
            ) -> NoReturn: ...

        @overload
        def translate(
            self,
            translatable: Translatable[NameType, IdType],
            names: ExplicitNames[NameType, SourceType] | None = None,
            *,
            ignore_names: Names[NameType] | None = None,
            copy: Literal[True] = True,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            max_fails: float = 1.0,
            reverse: Literal[False] = False,
            fmt: FormatType | None = None,
            io_kwargs: Mapping[str, Any] | None = None,
        ) -> Translatable[NameType, str]: ...

        @overload
        def translate(
            self,
            translatable: Translatable[NameType, str],
            names: ExplicitNames[NameType, SourceType] | None = None,
            *,
            ignore_names: Names[NameType] | None = None,
            copy: Literal[True] = True,
            override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
            max_fails: float = 1.0,
            reverse: Literal[True],
            fmt: FormatType | None = None,
            io_kwargs: Mapping[str, Any] | None = None,
        ) -> Translatable[NameType, IdType]: ...

    def translate(
        self,
        translatable: Translatable[NameType, IdType],
        names: ExplicitNames[NameType, SourceType] | None = None,
        *,
        ignore_names: Names[NameType] | None = None,
        copy: bool = True,
        override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
        max_fails: float = 1.0,
        reverse: bool = False,
        fmt: FormatType | None = None,
        io_kwargs: Mapping[str, Any] | None = None,
    ) -> Translatable[NameType, str] | None:
        """Translate IDs to human-readable strings.

        Simplified process:
            1. The :meth:`~id_translation.Translator.extract_names` method derives names of the `translatable` to translate (if needed).
            2. The :meth:`~id_translation.Translator.map` method performs name-to-source mapping (see
               :class:`~id_translation.mapping.DirectionalMapping`).
            3. The :meth:`~id_translation.Translator.fetch` method extracts IDs to translate and retrieves data (see
               :class:`~id_translation.offline.TranslationMap`).
            4. Finally, the ``translate()`` method (i.e. this one) applies the translations and returns to the caller.

        See the :ref:`translation-primer` page for a detailed process description.

        Args:
            translatable: A data structure to translate.
            names: Explicit names to translate. Derive from `translatable` if ``None``. Alternatively, you may pass a
                ``dict`` on the form ``{name_in_translatable: source_to_use}``.
            ignore_names: Names **not** to translate, or a predicate ``(NameType) -> bool``.
            copy: If ``False``, translate in-place and return ``None``.
            override_function: A callable ``(name, sources, context) -> Source | None``, where `context` is always
                ``None``. See :meth:`Mapper.apply <id_translation.mapping.Mapper.apply>` for details.
            max_fails: The maximum fraction of IDs for which translation may fail. 1=disabled. Missing values (``NaN``,
                null) in ``pandas``, ``dask``, ``polars`` and ``pyarrow`` data are pass-throughs and never count; in a
                builtin collection or array, ``None`` and ``NaN`` are ordinary (unknown) IDs, and do.
            reverse: If ``True``, perform translations back to IDs. Offline mode only.
            fmt: A :class:`format string <id_translation.offline.Format>` such as **'{id}:{name}'** to use. Default is
                :attr:`Translator.fmt <id_translation.Translator.fmt>`.
            io_kwargs: Keyword arguments for the IO class (e.g.
                :class:`~id_translation.dio.integration.pandas.PandasIO`).

        Returns:
            A translated copy of `translatable` if ``copy=True``, otherwise ``None``.

        Examples:
            Manual :ref:`name-to-source <name-to-source-mapping>` mapping with a temporary name-only
            :class:`~id_translation.offline.Format`.

            ..
               # Hidden setup code
               >>> translator = Translator({"animals": {"id": [2], "name": ["Simba"]}})

            >>> n2s = {"lions": "animals", "big_cats": "animals"}
            >>> translator.translate({"lions": 2, "big_cats": 2}, names=n2s, fmt="{name}")
            {'lions': 'Simba', 'big_cats': 'Simba'}

            Name mappings must be complete; any name not present in the keys will be ignored (left as-is).

        Raises:
            ~id_translation.dio.exceptions.UntranslatableTypeError: If ``type(translatable)`` cannot be translated.
            ~id_translation.exceptions.MissingNamesError: If `names` are not given and cannot be derived from
                `translatable`.
            ~id_translation.mapping.exceptions.UnmappedExplicitNamesError: If any required (explicitly given) names fail
                to map to a source.
            ~id_translation.mapping.exceptions.MappingError: If name-to-source mapping fails, e.g.
                :class:`~id_translation.mapping.exceptions.ScoringDisabledError` for a name that is neither a source
                nor overridden, when using the default :class:`~id_translation.mapping.Mapper`.
            ~id_translation.exceptions.MissingPlaceholderError: If a source lacks a placeholder that `fmt` requires.
            ValueError: If `max_fails` is not a valid fraction.
            ~id_translation.exceptions.TooManyFailedTranslationsError: If translation fails for more than `max_fails` of
                IDs.
            ~id_translation.exceptions.ConnectionStatusError: If ``reverse=True`` while the
                :class:`~id_translation.Translator` is online.
            ~id_translation.mapping.exceptions.UserMappingError: If `override_function` returns a source which is not
                known, and ``mapper.on_unknown_user_override='raise'``.

        See Also:
            🔑 This is a key event method. See :ref:`key-events` for details.

            The :envvar:`ID_TRANSLATION_DISABLED` variable.

            The first call runs :meth:`~id_translation.Translator.initialize_sources`; see it for what it raises.
        """
        if read_bool(ID_TRANSLATION_DISABLED):
            message = f"Translation aborted; {ID_TRANSLATION_DISABLED} is set."
            LOGGER.warning(message)
            emit_warning(message, category=TranslationDisabledWarning, logged=True)
            return translatable if copy else None  # Return unchanged; breaks typing.

        if self.online and reverse:  # pragma: no cover
            raise ConnectionStatusError("Reverse translation cannot be performed online.")

        task_id = _logging.generate_task_id()
        self.initialize_sources(task_id=task_id)

        task = TranslationTask(
            self,
            translatable,
            self._fmt if fmt is None else Format.parse(fmt),
            names,
            ignore_names=ignore_names,
            override_function=override_function,
            copy=copy,
            max_fails=max_fails,
            reverse=reverse,
            enable_uuid_heuristics=self._enable_uuid_heuristics,
            io_kwargs=io_kwargs,
            event_key=f"{type(self).__name__}.{self.translate.__name__}",
            task_id=task_id,
        )
        task.log_key_event_enter()

        translation_map = self._get_updated_tmap(task)
        if not task.name_to_source:
            # Return unchanged; this is technically against the API spec. If the user has required translation to
            # success through configuration, exceptions will be raised elsewhere. I don't know how to express this using
            # the Python type system.
            return translatable if copy else None

        if translation_map:  # Empty when no mapped name had IDs: nothing was fetched, and nothing can fail.
            task.verify(translation_map)

        ans = task.insert(translation_map)

        self._translated_names = (task_id, dict(task.name_to_source))
        task.finished()
        task.log_key_event_exit()
        return ans

    @overload
    def translated_names(self, with_source: Literal[True]) -> NameToSource[NameType, SourceType]: ...

    @overload
    def translated_names(self, with_source: Literal[False] = False) -> list[NameType]: ...

    def translated_names(self, with_source: bool = True) -> NameToSource[NameType, SourceType] | list[NameType]:
        """Return the names translated by the last successful :meth:`~id_translation.Translator.translate`-call.

        A call is successful if it translates at least one name. Calls that raise or abort leave the result unchanged:
        when no name maps to a source, or when ``ID_TRANSLATION_DISABLED`` is set.

        Args:
            with_source: If ``True``, return a dict ``{name: source}`` instead of a list.

        Returns:
            Recent names translated by this :class:`~id_translation.Translator`, in **arbitrary** order.

        Raises:
            ValueError: If no names have been translated using this :class:`~id_translation.Translator`.

        Notes:
            🧵 This method is not thread safe. See :ref:`thread-safety` for details.
        """
        if self._translated_names is None:
            raise ValueError("No names have been translated using this Translator.")
        task_id, name_to_source = self._translated_names
        LOGGER.debug(f"Returning names translated by task with {task_id=}.", extra=dict(task_id=task_id))
        return dict(name_to_source) if with_source else list(name_to_source)

    @overload
    def extract_names(
        self,
        translatable: Translatable[NameType, IdType],
        *,
        ignore_names: Names[NameType] | None = None,
        io_kwargs: Mapping[str, Any] | None = None,
        raising: Literal[False] = False,
    ) -> list[NameType] | None: ...

    @overload
    def extract_names(
        self,
        translatable: Translatable[NameType, IdType],
        *,
        ignore_names: Names[NameType] | None = None,
        io_kwargs: Mapping[str, Any] | None = None,
        raising: Literal[True],
    ) -> list[NameType]: ...

    def extract_names(
        self,
        translatable: Translatable[NameType, IdType],
        *,
        ignore_names: Names[NameType] | None = None,
        io_kwargs: Mapping[str, Any] | None = None,
        raising: bool = False,
    ) -> list[NameType] | None:
        """Extract names in `translatable`.

        Perform name extraction. The `names` are the first input to the :meth:`~id_translation.Translator.map` method,
        with the second being the :attr:`~id_translation.Translator.sources`. Does not call
        :meth:`~id_translation.Translator.initialize_sources`.

        Args:
            translatable: A data structure to map names for.
            ignore_names: Names **not** to translate, or a predicate ``(NameType) -> bool``.
            io_kwargs: Keyword arguments for the IO class (e.g.
                :class:`~id_translation.dio.integration.pandas.PandasIO`).
            raising: If ``False`` (the default), return ``None`` instead of raising
                :class:`~id_translation.exceptions.MissingNamesError` when name extraction fails.

        Returns:
            Names to map to sources.

        Raises:
            ~id_translation.exceptions.MissingNamesError: If `names` cannot be derived (only when ``raising=True``).
        """
        task = NamesTask(self, translatable, ignore_names=ignore_names, io_kwargs=io_kwargs)

        if raising:
            return task.mapper_input_names

        try:
            return task.mapper_input_names
        except MissingNamesError:
            return None

    def map(
        self,
        translatable: Translatable[NameType, IdType],
        names: ExplicitNames[NameType, SourceType] | None = None,
        *,
        ignore_names: Names[NameType] | None = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
        io_kwargs: Mapping[str, Any] | None = None,
    ) -> NameToSource[NameType, SourceType]:
        """Map names to translation sources.

        Args:
            translatable: A data structure to map names for.
            names: Explicit names to translate. Derive from `translatable` if ``None``. Alternatively, you may pass a
                ``dict`` on the form ``{name_in_translatable: source_to_use}``.
            ignore_names: Names **not** to translate, or a predicate ``(NameType) -> bool``.
            override_function: A callable ``(name, sources, context) -> Source | None``, where `context` is always
                ``None``. See :meth:`Mapper.apply <id_translation.mapping.Mapper.apply>` for details.
            io_kwargs: Keyword arguments for the IO class (e.g.
                :class:`~id_translation.dio.integration.pandas.PandasIO`).

        Returns:
            A mapping of names to translation sources.

        Raises:
            ~id_translation.exceptions.MissingNamesError: If `names` are not given and cannot be derived from
                `translatable`.
            ~id_translation.mapping.exceptions.UnmappedExplicitNamesError: If any required (explicitly given) names fail
                to map to a source.
            ~id_translation.mapping.exceptions.MappingError: If name-to-source mapping fails, e.g.
                :class:`~id_translation.mapping.exceptions.ScoringDisabledError` for a name that is neither a source
                nor overridden, when using the default :class:`~id_translation.mapping.Mapper`.
            ~id_translation.mapping.exceptions.UserMappingError: If `override_function` returns a source which is not
                known, and ``mapper.on_unknown_user_override='raise'``.

        See Also:
            🔑 This is a key event method. See :ref:`key-events` for details.

            The :meth:`~id_translation.Translator.extract_names` method.

            The first call runs :meth:`~id_translation.Translator.initialize_sources`; see it for what it raises.
        """
        task_id = _logging.generate_task_id()
        self.initialize_sources(task_id=task_id)

        return MappingTask(
            self,
            translatable,
            names,
            ignore_names=ignore_names,
            override_function=override_function,
            io_kwargs=io_kwargs,
            task_id=task_id,
        ).name_to_source

    def map_scores(
        self,
        translatable: Translatable[NameType, IdType],
        names: ExplicitNames[NameType, SourceType] | None = None,
        *,
        ignore_names: Names[NameType] | None = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
        io_kwargs: Mapping[str, Any] | None = None,
    ) -> ScoreMatrix[NameType, SourceType]:
        """Returns raw match scores for name-to-source mapping. See :meth:`~id_translation.Translator.map` for details."""
        return MappingTask(
            self,
            translatable,
            names,
            ignore_names=ignore_names,
            override_function=override_function,
            io_kwargs=io_kwargs,
        ).compute_scores()

    @property
    def sources(self) -> list[SourceType]:
        """A list of known source names.

        Sources are determined either by the :attr:`~id_translation.Translator.fetcher` or the
        :attr:`~id_translation.Translator.cache`.
        """
        if not self.online and self._cached_tmap is not None:
            # Not by way of `placeholders`: that property copies every per-source placeholder list.
            return self._cached_tmap.sources
        return list(self.placeholders)

    @property
    def placeholders(self) -> Mapping[SourceType, Sequence[str]]:
        """A mapping ``{source: [placeholders, ...]}``.

        Placeholders shown here are the names as they appear **in the source**.
        """
        if self.online:
            if not self._tx.discovered:
                with self._tx.lock:  # Discovery from here must not race a first translation.
                    return self.fetcher.placeholders
            return self.fetcher.placeholders

        assert self._cached_tmap is not None, "bad internal state"  # noqa: S101
        return self._cached_tmap.placeholders

    @property
    def fmt(self) -> Format:
        """Main translation :class:`~id_translation.offline.Format` for this ``Translator`` instance."""
        return self._fmt

    @property
    def default_fmt(self) -> Format:
        """Alternative translation :class:`~id_translation.offline.Format`, used for unknown IDs."""
        return self._default_fmt

    @property
    def enable_uuid_heuristics(self) -> bool:
        """Improves matching when :py:class:`~uuid.UUID`-like IDs are in use."""
        return self._enable_uuid_heuristics

    @property
    def online(self) -> bool:
        """Return connectivity status. If ``False``, no new translations may be fetched."""
        return self._fetcher is not None

    @property
    def fetcher(self) -> Fetcher[SourceType, IdType]:
        """Return the :class:`~id_translation.fetching.Fetcher` instance used to retrieve translations."""
        # Not `self.online`: narrowing the attribute here is what lets the rest of the class use this property
        # without a guard of its own.
        if self._fetcher is None:
            raise ConnectionStatusError(
                "Cannot fetch new translations.",
                hints="Use the Translator.cache-property to access the data.",
            )

        return self._fetcher

    @property
    def mapper(self) -> Mapper[NameType, SourceType, None]:
        """Return the :class:`~id_translation.mapping.Mapper` instance used for name-to-source binding."""
        return self._mapper

    @property
    def cache(self) -> TranslationMap[NameType, SourceType, IdType]:
        """Return a :class:`~id_translation.offline.TranslationMap` of cached translations."""
        if self._cached_tmap is None:
            assert self.online, "bad internal state"  # noqa: S101
            msg = f"No cache available. Use `{self.go_offline.__qualname__}` to cache translations."
            raise RuntimeError(msg)
        return self._cached_tmap

    @classmethod
    def load_persistent_instance(
        cls,
        cache_dir: AnyPath,
        config_path: AnyPath,
        extra_fetchers: AnyPath | Iterable[AnyPath] = (),
        max_age: str | timedelta | None = "12h",
        on_config_changed: Literal["raise", "recreate"] = "recreate",
    ) -> Self:
        """Load or create a persistent, offline :class:`~id_translation.Translator`.

        Instances are created, stored and loaded as determined by a metadata file located in the given `cache_dir`. A
        new :class:`~id_translation.Translator` will be created if:

        * There is no `'metadata'` file, or it cannot be parsed, or
        * the cached instance cannot be restored, e.g. because it is missing or was only partly written, or
        * the original :class:`~id_translation.Translator` is too old (see `max_age`), or
        * the current configuration, as defined by `config_path` and `extra_fetchers`, has changed in such a way
          that it is no longer equivalent to the configuration used to create the original
          :class:`~id_translation.Translator`. Equivalence also covers the ``Translator`` class, ``metaconf.toml``,
          and the Python and package versions, so upgrading ``id-translation`` counts as a change. For details, see
          :class:`~id_translation.toml.meta.ConfigMetadata`.

        Args:
            cache_dir: Root directory where the cached translator and associated metadata is stored.
            config_path: Path to the main TOML configuration file.
            extra_fetchers: A path, or paths, to fetching configuration TOML files. If multiple fetchers are defined,
                they are ranked by input order. A fetcher defined in the main configuration is prioritized (rank=0).
            max_age: The maximum age of the cached :class:`~id_translation.Translator` before it must be recreated. Pass
                ``'0s'`` or ``timedelta(0)`` to force recreation, or ``None`` to ignore.
            on_config_changed: One of ``raise|recreate``. If ``'raise'``, crash instead of creating a new instance if
                the configuration (as determined by `config_path` and `extra_fetchers`) has changed, including after a
                version upgrade.

        Returns:
            A new or cached :class:`~id_translation.Translator` instance with a
            :attr:`~id_translation.Translator.config_metadata` attribute.

        Raises:
            ~id_translation.exceptions.ConfigurationChangedError: If the configuration has changed and
                ``on_config_changed='raise'``.

        Notes:
            🧵 This method is not thread safe. See :ref:`thread-safety` for details.

        See Also:
            The :meth:`~id_translation.Translator.from_config` method, which will read the `config_path`.
        """
        path = any_path_to_path(config_path).expanduser()
        cache_dir = any_path_to_path(cache_dir).expanduser().absolute()
        cache_dir.mkdir(parents=True, exist_ok=True)

        metadata_path = cache_dir / "metadata.json"
        cache_path = cache_dir / "translator.pkl"

        fetcher_paths: list[AnyPath] = as_list(extra_fetchers)  # A bare path is one path, not characters.
        extra_fetcher_paths = [str(any_path_to_path(p).expanduser()) for p in fetcher_paths]

        metadata = meta.ConfigMetadata.from_toml_paths(
            str(path),
            extra_fetcher_paths,
            clazz=cls,
        )
        use_cached, reason, reason_type = metadata.use_cached(metadata_path, max_age)
        if use_cached:
            try:
                cached = cls.restore(cache_path)
            except Exception as e:  # Missing, torn or incompatible: a cache miss like any other.
                if isinstance(e, OSError) and not isinstance(e, FileNotFoundError):
                    raise  # E.g. no permission: fail now rather than after recreating, which may not fix it.
                reason = f"cached instance is unreadable: {e!r}"
            else:
                LOGGER.info(f"Reuse existing Translator; {reason}. Cache dir: '{cache_dir}'.")
                return cached

        if reason_type == "metadata-changed" and on_config_changed.lower() == "raise":
            exc = ConfigurationChangedError(reason, cache_dir=str(cache_dir))
            add_hints(
                exc, f"Pass on_config_changed='recreate', or delete the cache directory '{cache_dir}', to rebuild it."
            )
            raise exc

        LOGGER.info(f"Create new Translator; {reason}. Cache dir: '{cache_dir}'.")
        translator = cls.from_config(path, extra_fetcher_paths)
        translator.go_offline(path=cache_path)
        # Last, and replaced atomically like the snapshot: metadata never vouches for a torn or missing snapshot.
        metadata_json = translator.config_metadata.to_json().encode("utf-8")
        replace_atomically(metadata_path, lambda f: f.write(metadata_json))
        return translator

    @classmethod
    def restore(cls, path: AnyPath) -> Self:
        """Restore a serialized :class:`~id_translation.Translator`.

        Args:
            path: Path to a serialized :class:`~id_translation.Translator`.

        Returns:
            A :class:`~id_translation.Translator`.

        Raises:
            TypeError: If the object at `path` is not a :class:`~id_translation.Translator` or a subtype thereof.
            ValueError: If the snapshot was written by an incompatible version. Snapshots are same-version
                artifacts; recreate it with :meth:`~id_translation.Translator.go_offline`.

        See Also:
            The :meth:`~id_translation.Translator.go_offline` method.
        """
        full_path = any_path_to_path(path).expanduser()
        with full_path.open("rb") as f:
            ans = pickle.load(f)  # noqa: S301

        if not isinstance(ans, cls):  # pragma: no cover
            raise TypeError(f"Serialized object at '{full_path}' is a {type(ans).__name__}, not {cls}.")

        if LOGGER.isEnabledFor(logging.DEBUG):
            extra = "" if ans._config_metadata is None else f" with {ans.config_metadata}"
            LOGGER.debug(f"Deserialized {ans}{extra}.")

        return ans

    def go_offline(
        self,
        translatable: Translatable[NameType, IdType] | None = None,
        names: ExplicitNames[NameType, SourceType] | None = None,
        *,
        ignore_names: Names[NameType] | None = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
        max_fails: float = 1.0,
        fmt: FormatType | None = None,
        io_kwargs: Mapping[str, Any] | None = None,
        path: AnyPath | None = None,
    ) -> Self:
        """Retrieve and :attr:`~id_translation.Translator.cache` translations in memory.

        .. warning::

           The :attr:`~id_translation.Translator.fetcher` will be destroyed.

        Args:
            translatable: Data from which IDs to fetch will be extracted. Fetch all IDs if ``None``.
            names: Explicit names to translate. Derive from `translatable` if ``None``.
            ignore_names: Names **not** to translate, or a predicate ``(NameType) -> bool``.
            override_function: A callable ``(name, sources, context) -> Source | None``, where `context` is always
                ``None``. See :meth:`Mapper.apply <id_translation.mapping.Mapper.apply>` for details.
            max_fails: The maximum fraction of IDs for which translation may fail. 1=disabled. Requires `translatable`.
                Missing IDs (e.g. ``NaN``) in ``pandas`` types are pass-throughs and never count; a ``None`` in a
                builtin collection is an ordinary (unknown) ID, and does.
            fmt: A :class:`format string <id_translation.offline.Format>` such as **'{id}:{name}'** to use. Default is
                :attr:`Translator.fmt <id_translation.Translator.fmt>`. The snapshot is only guaranteed to hold the
                placeholders of `fmt`; list any others that a later `translate()` needs as optional blocks, e.g.
                ``'{id}:{name}[ {team}]'``.
            io_kwargs: Keyword arguments for the IO class (e.g.
                :class:`~id_translation.dio.integration.pandas.PandasIO`).
            path: If given, serialize the :class:`~id_translation.Translator` to disk after retrieving data.

        Returns:
            Self, for chained assignment.

        Raises:
            ~id_translation.exceptions.ConnectionStatusError: If already disconnected from the fetcher, i.e. not
                :attr:`~id_translation.Translator.online`.
            ~id_translation.fetching.exceptions.ForbiddenOperationError: If ``translatable=None`` and
                :meth:`Fetcher.fetch_all <id_translation.fetching.Fetcher.fetch_all>` is disabled.
            ValueError: If `io_kwargs` or `max_fails` is given without `translatable`.
            ~id_translation.mapping.exceptions.MappingError: If :meth:`~id_translation.Translator.map` fails (only when
                `translatable` is given).
            ~id_translation.exceptions.NoSourcesError: If the snapshot would hold no sources, unless the ``Translator``
                was accepted without any (`require_sources=False`). The ``Translator`` stays online.

        Notes:
            The transformers :ref:`settle <transformation-primer-settling>` against the snapshot, dropping those for
            sources outside it.

            🧵 This method is not thread safe. See :ref:`thread-safety` for details.

            The :class:`~id_translation.Translator` is guaranteed to be :func:`~rics.misc.serializable` once offline.
            Fetchers often aren't as they require things like database connections to function.

        See Also:
            🔑 This is a key event method. See :ref:`key-events` for details.

            The :meth:`~id_translation.Translator.restore` method (when `path` is set).
        """
        if not self.online:
            raise ConnectionStatusError("Translator is already offline.")

        start = perf_counter()
        task_id = _logging.generate_task_id(start)
        self.initialize_sources(task_id=task_id)

        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug(
                msg=f"Begin going offline with {len(self.sources)} sources provided by: {self.fetcher}",
                extra=dict(
                    task_id=task_id,
                    event_key=_logging.get_event_key(self.go_offline, "enter"),
                    # Task-specific
                    path=None if path is None else str(path),
                    translatable_type=None if translatable is None else tname(translatable, include_module=True),
                ),
            )

        translation_map = self._user_fetch(
            translatable,
            names,
            ignore_names=ignore_names,
            override_function=override_function,
            max_fails=max_fails,
            fmt=fmt,
            io_kwargs=io_kwargs,
            func=self.go_offline.__qualname__,
            task_id=task_id,
        )
        if not translation_map.sources and self._serves_sources():
            # A Translator without sources gets here only through initialize_sources(require_sources=False); such a
            # Translator goes offline with an empty snapshot. Raise before closing the fetcher: raising afterwards
            # would leave a Translator that is neither online nor offline.
            if translatable is not None:
                hint = "No name in the translatable mapped to a source with IDs to fetch."
            elif any(arg is not None for arg in (names, ignore_names, override_function)):
                hint = (
                    "No source was selected, or every selected source was skipped; check `names`, `ignore_names` and"
                    " `override_function`, and see the log for required placeholders that could not be mapped."
                )
            else:
                hint = "Every source was skipped; see the log for required placeholders that could not be mapped."
            raise NoSourcesError("Nothing to take offline: the snapshot would hold no sources.", hints=hint)
        self.fetcher.close()
        self._fetcher = None
        self._cached_tmap = translation_map
        # A snapshot may cover a subset of the original sources on purpose, so trim to what it can actually serve.
        self._tx.freeze(self, translation_map.sources, report=False)

        if path:
            path = any_path_to_path(path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            replace_atomically(path, lambda f: pickle.dump(self, f))

            cls = tname(self, include_module=True)
            LOGGER.info(
                f"Serialized '{cls}' of size {path.stat().st_size / 2**20:.2g} MiB at path='{path}'.",
                extra=dict(
                    task_id=task_id,
                    event_key=_logging.get_event_key(self.go_offline, "serialize"),
                    # Task-specific
                    path=str(path),
                    translatable_type=None if translatable is None else tname(translatable, include_module=True),
                ),
            )

        if LOGGER.isEnabledFor(logging.INFO):
            seconds = perf_counter() - start
            LOGGER.info(
                f"Went offline with {len(translation_map.sources)} sources in {fmt_sec(seconds)}: {translation_map}.",
                extra=dict(
                    task_id=task_id,
                    event_key=_logging.get_event_key(self.go_offline, "exit"),
                    seconds=seconds,
                    # Task-specific
                    path=None if path is None else str(path),
                    translatable_type=None if translatable is None else tname(translatable, include_module=True),
                ),
            )

        return self

    def fetch(
        self,
        translatable: Translatable[NameType, IdType] | None = None,
        names: ExplicitNames[NameType, SourceType] | None = None,
        *,
        ignore_names: Names[NameType] | None = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
        max_fails: float = 1.0,
        fmt: FormatType | None = None,
        io_kwargs: Mapping[str, Any] | None = None,
    ) -> TranslationMap[NameType, SourceType, IdType]:
        """Fetch translations.

        Calling ``fetch`` without arguments will perform a
        :meth:`Fetcher.fetch_all <id_translation.fetching.Fetcher.fetch_all>` -operation, without going offline.

        .. hint::

           Use :meth:`TranslationMap.to_dicts() <id_translation.offline.TranslationMap.to_dicts>` to convert the
           result to native types.

        Args:
            translatable: Data from which IDs to fetch will be extracted. Fetch all IDs if ``None``.
            names: Explicit names to translate. Derive from `translatable` if ``None``. Alternatively, you may pass a
                ``dict`` on the form ``{name_in_translatable: source_to_use}``.
            ignore_names: Names **not** to translate, or a predicate ``(NameType) -> bool``.
            override_function: A callable ``(name, sources, context) -> Source | None``, where `context` is always
                ``None``. See :meth:`Mapper.apply <id_translation.mapping.Mapper.apply>` for details.
            max_fails: The maximum fraction of IDs for which translation may fail. 1=disabled. Requires `translatable`.
                Missing IDs (e.g. ``NaN``) in ``pandas`` types are pass-throughs and never count; a ``None`` in a
                builtin collection is an ordinary (unknown) ID, and does.
            fmt: A :class:`format string <id_translation.offline.Format>` such as **'{id}:{name}'** to use. Default is
                :attr:`Translator.fmt <id_translation.Translator.fmt>`.
            io_kwargs: Keyword arguments for the IO class (e.g.
                :class:`~id_translation.dio.integration.pandas.PandasIO`).

        Returns:
            A :class:`~id_translation.offline.TranslationMap`.

        Raises:
            ~id_translation.exceptions.ConnectionStatusError: If disconnected from the fetcher, i.e. not
                :attr:`~id_translation.Translator.online`.
            ~id_translation.fetching.exceptions.ForbiddenOperationError: If ``translatable=None`` and
                :meth:`Fetcher.fetch_all <id_translation.fetching.Fetcher.fetch_all>` is disabled.
            ValueError: If `io_kwargs` or `max_fails` is given without `translatable`.
            ~id_translation.dio.exceptions.UntranslatableTypeError: If ``type(translatable)`` cannot be translated.
            ~id_translation.exceptions.MissingNamesError: If `names` are not given and cannot be derived.
            ~id_translation.exceptions.MissingNamesError: If `names` are given but missing from key-based data such as
                a ``dict`` or ``DataFrame``.
            ~id_translation.mapping.exceptions.UnmappedExplicitNamesError: If a required name fails to map to a source.
            ~id_translation.mapping.exceptions.MappingError: If name-to-source mapping fails.
            ~id_translation.exceptions.MissingPlaceholderError: If a source lacks a placeholder that `fmt` requires.
            ~id_translation.exceptions.TooManyFailedTranslationsError: If translation fails for over `max_fails` of IDs.
            ~id_translation.mapping.exceptions.UserMappingError: If `names` maps a name to an
                unknown :attr:`source <id_translation.Translator.sources>`.
            ~id_translation.mapping.exceptions.UserMappingError: If `override_function` returns an unknown
                :attr:`source <id_translation.Translator.sources>` and ``mapper.on_unknown_user_override='raise'``.
            ~id_translation.mapping.exceptions.BadOverrideError: If an override of the mapper maps a name to an
                unknown :attr:`source <id_translation.Translator.sources>`.

        See Also:
            The first call runs :meth:`~id_translation.Translator.initialize_sources`; see it for what it raises.

        Examples:
            Basic usage.

            ..
               # Hidden setup code
               >>> from id_translation.fetching import MemoryFetcher
               >>> translation_data = {
               ...     "animals": {"id": [0, 1, 2], "name": ["Tarzan", "Morris", "Simba"]},
               ...     "people": {"id": [1999, 1991], "name": ["Sofia", "Richard"]},
               ... }
               >>> translator = Translator(MemoryFetcher(translation_data))

            >>> translation_map = translator.fetch()
            >>> translation_map
            TranslationMap('animals': 3 IDs, 'people': 2 IDs)

            See :class:`~id_translation.offline.TranslationMap` for details.
        """
        task_id = _logging.generate_task_id()
        self.initialize_sources(task_id=task_id)

        return self._user_fetch(
            translatable,
            names,
            ignore_names=ignore_names,
            override_function=override_function,
            max_fails=max_fails,
            fmt=fmt,
            io_kwargs=io_kwargs,
            func=self.fetch.__qualname__,
            task_id=task_id,
        )

    def _user_fetch(
        self,
        translatable: Translatable[NameType, IdType] | None = None,
        names: ExplicitNames[NameType, SourceType] | None = None,
        *,
        ignore_names: Names[NameType] | None = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
        max_fails: float = 1.0,
        fmt: FormatType | None = None,
        io_kwargs: Mapping[str, Any] | None = None,
        func: str,
        task_id: int | None = None,
    ) -> TranslationMap[NameType, SourceType, IdType]:
        if io_kwargs and translatable is None:
            raise ValueError(f"Got {io_kwargs=}, but {translatable=}; io_kwargs requires a translatable.")
        if max_fails != 1.0 and translatable is None:
            raise ValueError(f"Got {max_fails=}, but {translatable=}; max_fails requires a translatable.")

        fmt = self._fmt if fmt is None else Format.parse(fmt)

        if translatable is None:
            if all(p is None for p in (names, ignore_names, override_function)):
                source_translations = self._fetch(None, fmt, task_id=task_id)
            else:
                dummy = {source: None for source in self.sources}
                sources = self.map(dummy, names, ignore_names=ignore_names, override_function=override_function)
                source_translations = self._fetch(set(sources.values()), fmt, task_id=task_id)
            translation_map = self._to_translation_map(source_translations, fmt=fmt)

            if names is None:
                pass  # Callers must perform mapping unless name=source.
            elif isinstance(names, Mapping):
                translation_map.name_to_source = dict(names)
            else:
                translation_map.name_to_source = self.mapper.apply(
                    as_list(names),
                    translation_map.sources,
                    override_function=override_function,
                    task_id=task_id,
                ).flatten()
        else:
            task = TranslationTask(
                self,
                translatable,
                fmt,
                names,
                ignore_names=ignore_names,
                override_function=override_function,
                max_fails=max_fails,
                enable_uuid_heuristics=self._enable_uuid_heuristics,
                io_kwargs=io_kwargs,
                event_key=func,
                task_id=task_id,
            )

            translation_map = self._get_updated_tmap(task, force_fetch=True)
            task.verify(translation_map)

        return translation_map

    def _get_updated_tmap(
        self,
        task: TranslationTask[NameType, SourceType, IdType],
        force_fetch: bool = False,
    ) -> TranslationMap[NameType, SourceType, IdType]:
        """Get an updated translation map."""
        if not task.name_to_source:
            source_translations = {}  # Nothing to translate.
        elif force_fetch or self._cached_tmap is None:
            source_translations = self._execute_fetch(task)
        else:
            source_translations = self._cached_tmap._extract_translations()

        return self._to_translation_map(source_translations, task.fmt, task.name_to_source)

    @property
    def transformers(self) -> Mapping[SourceType, Transformer[IdType]]:
        """Get a read-only view ``{source: transformer}``.

        See :meth:`~id_translation.Translator.register_transformer` to add them.

        Returns:
            A read-only view with one transformer per source. Chains are
            a single :class:`~id_translation.transform.TransformerStack`.

        Raises:
            ~id_translation.exceptions.TransformerStateError: If not :ref:`settled <transformation-primer-settling>`.
        """
        return self._tx.transformers

    def register_transformer(
        self,
        source: SourceType,
        transformer: Transformer[IdType] | Sequence[Transformer[IdType]],
        *,
        on_existing: OnExistingTransformer = "raise",
    ) -> None:
        """Register `transformer` for `source`.

        Creates a :class:`~id_translation.transform.TransformerStack` when called
        multiple times with ``on_existing='append'``.

        .. hint::

           See the :ref:`transformation-primer` for chaining priority rules and usage examples.

        Args:
            source: The source to transform.
            transformer: A :class:`~id_translation.transform.types.Transformer`, or a sequence to chain in order.
            on_existing: Action to take when `source` already has a transformer. Use ``'append'`` to chain onto it, or
                ``'overwrite'`` to discard it.

        Raises:
            ValueError: If `transformer` is an empty sequence.
            ~id_translation.exceptions.TransformerConflictError: If `source` is registered and ``on_existing='raise'``.
            ~id_translation.exceptions.TransformerStateError: If :ref:`settled <transformation-primer-settling>`.
        """
        self._tx.register(source, transformer, on_existing)

    def _execute_fetch(
        self,
        task: TranslationTask[NameType, SourceType, IdType],
    ) -> SourcePlaceholderTranslations[SourceType]:
        start = perf_counter()

        ids_to_fetch = [IdsToFetch(source, ids=ids) for source, ids in task.extract_ids().items()]

        transformers = self._tx.settled(self)
        for itf in ids_to_fetch:
            transformer = transformers.get(itf.source)
            if transformer is not None:
                transformer.update_ids(itf.ids)

        source_translations = self._fetch(ids_to_fetch, fmt=task.fmt, task_id=task.task_id)
        task.add_timing("fetch", perf_counter() - start)
        return source_translations

    def _fetch(
        self,
        ids_or_sources: list[IdsToFetch[SourceType, IdType]] | set[SourceType] | None,
        fmt: Format,
        task_id: int | None,
    ) -> SourcePlaceholderTranslations[SourceType]:
        placeholders = fmt.placeholders
        placeholder_attributes = fmt.placeholder_attributes
        required = fmt.required_placeholders

        if self._default_fmt and ID in self._default_fmt.placeholders and ID not in placeholders:
            # Ensure that default translations can always use the ID
            placeholders = (*placeholders, ID)
            required = (*required, ID)

        if task_id is None:
            task_id = _logging.generate_task_id()

        if ids_or_sources is None or isinstance(ids_or_sources, set):
            return self.fetcher.fetch_all(
                placeholders,
                required=required,
                placeholder_attributes=placeholder_attributes,
                sources=ids_or_sources,
                task_id=task_id,
                enable_uuid_heuristics=self._enable_uuid_heuristics,
            )
        else:
            return self.fetcher.fetch(
                ids_or_sources,
                placeholders,
                required=required,
                placeholder_attributes=placeholder_attributes,
                task_id=task_id,
                enable_uuid_heuristics=self._enable_uuid_heuristics,
            )

    def _to_translation_map(
        self,
        source_translations: SourcePlaceholderTranslations[SourceType],
        fmt: Format | None = None,
        name_to_source: NameToSource[NameType, SourceType] | None = None,
    ) -> TranslationMap[NameType, SourceType, IdType]:
        return TranslationMap(
            source_translations,
            fmt=fmt or self._fmt,
            default_fmt=self._default_fmt,
            name_to_source=name_to_source,
            default_fmt_placeholders=self._default_fmt_placeholders,
            enable_uuid_heuristics=self._enable_uuid_heuristics,
            transformers=self._tx.settled(self),
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
