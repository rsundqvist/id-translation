import logging
import warnings
from datetime import timedelta
from inspect import signature
from os import getenv
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Generic, Iterable, List, Literal, Optional, Set, Tuple, Type, Union

import numpy
import pandas as pd
from rics._internal_support.types import PathLikeType
from rics.collections.dicts import InheritedKeysDict, MakeType
from rics.collections.misc import as_list
from rics.misc import tname
from rics.performance import format_perf_counter, format_seconds

from . import _uuid_utils
from ._config_utils import ConfigMetadata
from .dio import DataStructureIO, resolve_io
from .dio.exceptions import UntranslatableTypeError
from .exceptions import (
    ConnectionStatusError,
    MissingNamesError,
    TooManyFailedTranslationsError,
    TranslationDisabledWarning,
)
from .factory import TranslatorFactory
from .fetching import Fetcher
from .fetching.types import IdsToFetch
from .mapping import DirectionalMapping, Mapper
from .mapping.exceptions import MappingError, MappingWarning
from .mapping.types import UserOverrideFunction
from .offline import Format, TranslationMap
from .offline.types import FormatType, PlaceholderTranslations, SourcePlaceholderTranslations
from .types import ID, HasSources, IdType, Names, NameToSource, NameType, NameTypes, SourceType, Translatable

LOGGER = logging.getLogger(__package__).getChild("Translator")

FetcherTypes = Union[
    TranslationMap[NameType, SourceType, IdType],
    Fetcher[SourceType, IdType],
    SourcePlaceholderTranslations[SourceType],
    Dict[SourceType, PlaceholderTranslations.MakeTypes],
]

ID_TRANSLATION_DISABLED: Literal["ID_TRANSLATION_DISABLED"] = "ID_TRANSLATION_DISABLED"


class Translator(Generic[NameType, SourceType, IdType], HasSources[SourceType]):
    """Translate IDs to human-readable labels.

    For an introduction to translation, see the :ref:`translation-primer` page.

    The recommended way of initializing ``Translator`` instances is the :meth:`from_config` method. For configuration
    file details, please refer to the :ref:`translator-config` page.

    The `Translator` is the main entry point for all translation tasks. Simplified translation process steps:

        1. The :attr:`map` method performs name-to-source mapping (see :class:`.mapping.DirectionalMapping`).
        2. The :attr:`fetch` method extracts IDs to translate and retrieves data (see :class:`.TranslationMap`).
        3. Finally, the :attr:`translate` method applies the translations and returns to the caller.

    Args:
        fetcher: A :class:`.Fetcher` or ready-to-use translations.
        fmt: String :class:`.Format` specification for translations.
        mapper: A :class:`~.mapping.Mapper` instance for binding names to sources.
        default_fmt: Alternative :class:`.Format` to use instead of `fmt` for fallback translation of unknown IDs.
        default_fmt_placeholders: Shared and/or source-specific default placeholder values for unknown IDs. See
            :meth:`rics.collections.dicts.InheritedKeysDict.make` for details.
        allow_name_inheritance: If ``True``, enable name resolution fallback to the parent `translatable` when
            translating with the ``attribute``-option. Allows nameless ``pandas.Index`` instances to inherit the name of
            a ``pandas.Series``.
        enable_uuid_heuristics: Enabling may improve matching when :py:class:`~uuid.UUID`-like IDs are in use.

    Notes:
        Untranslatable IDs will be ``None`` by default if neither `default_fmt` nor `default_fmt_placeholders` is given.
        Adding the `maximal_untranslated_fraction` option to :meth:`translate` will raise an exception if too many IDs
        are left untranslated. Note however that this verifiction step may be expensive.

    Examples:
        A minimal example. For a more complete use case, see the :ref:`dvdrental` example. Assume that we have data for
        people and animals as in the table below::

            people:                       animals:
                 id | name    | gender       id | name   | is_nice
              ------+---------+--------     ----+--------+---------
               1991 | Richard | Male          0 | Tarzan | false
               1999 | Sofia   | Female        1 | Morris | true
               1904 | Fred    | Male          2 | Simba  | true

        In most real cases we'd fetch this table from somewhere. In this case, however, there's so little data that we
        can simply enumerate the components needed for translation ourselves.

        >>> from id_translation import Translator
        >>> translation_data = {
        ...   'animals': {
        ...     'id': [0, 1, 2],
        ...     'name': ['Tarzan', 'Morris', 'Simba'],
        ...     'is_nice': [False, True, True]
        ...   },
        ...   'people': {
        ...     'id': [1999, 1991, 1904],
        ...     'name': ['Sofia', 'Richard', 'Fred']
        ...   },
        ... }
        >>> translator = Translator(translation_data, fmt='{id}:{name}[, nice={is_nice}]')

        We didn't define a :class:`.Mapper`, so the names must match exactly.

        >>> data = {'animals': [0, 2], 'people': [1991, 1999]}
        >>> for key, translated_table in translator.translate(data).items():
        >>>     print(f'Translations for {repr(key)}:')
        >>>     for translated_id in translated_table:
        >>>         print(f'    {repr(translated_id)}')
        Translations for 'animals':
            '0:Tarzan, nice=False'
            '2:Simba, nice=True'
        Translations for 'people':
            '1991:Richard'
            '1999:Sofia'

        Handling unknown IDs.

        >>> default_fmt_placeholders = dict(
        ...   default={'is_nice': 'Maybe?', 'name': "Bob"},
        ...   specific={'animals': {'name': 'Fido'}},
        >>> )
        >>> useless_database = {
        ...   'animals': {'id': [], 'name': []},
        ...   'people': {'id': [], 'name': []}
        >>> }
        >>> translator = Translator(
        ...   useless_database, default_fmt_placeholders=default_fmt_placeholders,
        ...   fmt='{id}:{name}[, nice={is_nice}]'
        ... )
        >>> data = {'animals': [0], 'people': [0]}
        >>> for key, translated_table in translator.translate(data).items():
        >>>     print(f'Translations for {repr(key)}:')
        >>>     for translated_id in translated_table:
        >>>         print(f'    {repr(translated_id)}')
        Translations for 'animals':
            '0:Fido, nice=Maybe?'
        Translations for 'people':
            '0:Bob, nice=Maybe?'

        Since we didn't give an explicit `default_fmt_placeholders`, the regular `fmt` is used instead. Formats can be
        plain strings, in which case translation will never explicitly fail unless the name itself fails to map and
        :attr:`Mapper.unmapped_values_action <.mapping.Mapper.unmapped_values_action>` is set to
        :attr:`ActionLevel.RAISE <rics.action_level.ActionLevel.RAISE>`.
    """

    def __init__(
        self,
        fetcher: FetcherTypes[NameType, SourceType, IdType] = None,
        fmt: FormatType = "{id}:{name}",
        mapper: Mapper[NameType, SourceType, None] = None,
        default_fmt: FormatType = None,
        default_fmt_placeholders: MakeType[SourceType, str, Any] = None,
        allow_name_inheritance: bool = True,
        enable_uuid_heuristics: bool = False,
    ) -> None:
        self._fmt = fmt if isinstance(fmt, Format) else Format(fmt)
        self._default_fmt_placeholders: Optional[InheritedKeysDict[SourceType, str, Any]]
        self._default_fmt_placeholders, self._default_fmt = _handle_default(
            self._fmt, default_fmt, default_fmt_placeholders
        )
        self._allow_name_inheritance = allow_name_inheritance
        self._enable_uuid_heuristics = enable_uuid_heuristics

        self._cached_tmap: TranslationMap[NameType, SourceType, IdType] = TranslationMap({})
        self._fetcher: Fetcher[SourceType, IdType]
        if fetcher is None:
            from .testing import TestFetcher, TestMapper

            self._fetcher = TestFetcher([])  # No explidecit sources
            if mapper:  # pragma: no cover
                warnings.warn(
                    f"Mapper instance {mapper} given; consider creating a TestFetcher([sources..])-instance manually.",
                    UserWarning,
                    stacklevel=2,
                )
            else:
                mapper = TestMapper()  # type: ignore
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
            tmap.default_fmt_placeholders = self._default_fmt_placeholders  # type: ignore
            self._cached_tmap = tmap
        else:
            raise TypeError(type(fetcher))  # pragma: no cover

        self._mapper: Mapper[NameType, SourceType, None] = mapper or Mapper()
        self._mapper.logger = logging.getLogger(__package__).getChild("mapping").getChild("name-to-source")

        self._config_metadata: Optional[ConfigMetadata] = None
        self._translated_names: Optional[List[NameType]] = None

    @classmethod
    def from_config(
        cls,
        path: PathLikeType,
        extra_fetchers: Iterable[PathLikeType] = (),
        clazz: Union[str, Type["Translator[NameType, SourceType, IdType]"]] = None,
    ) -> "Translator[NameType, SourceType, IdType]":
        """Create a ``Translator`` from TOML inputs.

        Args:
            path: Path to the main TOML configuration file.
            extra_fetchers: Paths to fetching configuration TOML files. If multiple fetchers are defined, they are
                ranked by input order. If a fetcher defined in the main configuration, it will be prioritized (rank=0).
            clazz: Translator implementation to create. If a string is passed, the class is resolved using
                :func:`~rics.misc.get_by_full_name` if a string is given. Use ``cls`` if ``None``.

        Returns:
            A new ``Translator`` instance with a :attr:`config_metadata` attribute.
        """
        return TranslatorFactory(
            path,
            extra_fetchers,
            clazz or cls,  # TODO: Higher-Kinded TypeVars
        ).create()

    @property
    def config_metadata(self) -> ConfigMetadata:
        """Return :func:`from_config` initialization metadata."""
        if self._config_metadata is None:
            raise ValueError("Not created using Translator.from_config()")  # pragma: no cover
        return self._config_metadata

    def copy(self, share_fetcher: bool = True, **overrides: Any) -> "Translator[NameType, SourceType, IdType]":
        """Make a copy of this ``Translator``.

        Args:
            share_fetcher: If ``True``, the returned instance use the same ``Fetcher``.
            overrides: Keyword arguments to use when instantiating the copy. Options that aren't given will be taken
                from the current instance. See the :class:`Translator` class documentation for possible choices.

        Returns:
            A copy of this ``Translator`` with `overrides` applied.

        Raises:
            NotImplementedError: If ``share_fetcher=False``.
        """
        if not share_fetcher:
            raise NotImplementedError("Fetcher cloning not implemented.")

        kwargs: Dict[str, Any] = {
            "fmt": self._fmt,
            "default_fmt": self._default_fmt,
            "allow_name_inheritance": self._allow_name_inheritance,
            "enable_uuid_heuristics": self._enable_uuid_heuristics,
            **overrides,
        }

        if "mapper" not in kwargs:  # pragma: no cover
            kwargs["mapper"] = self.mapper.copy()
        if "default_fmt_placeholders" not in kwargs:
            kwargs["default_fmt_placeholders"] = self._default_fmt_placeholders
        if "fetcher" not in kwargs:
            kwargs["fetcher"] = self.fetcher if self.online else self._cached_tmap.copy()

        return type(self)(**kwargs)

    def translate(
        self,
        translatable: Translatable,
        names: Union[NameTypes[NameType], NameToSource[NameType, SourceType]] = None,
        ignore_names: Names[NameType] = None,
        inplace: bool = False,
        override_function: UserOverrideFunction[NameType, SourceType, None] = None,
        maximal_untranslated_fraction: float = 1.0,
        reverse: bool = False,
        attribute: str = None,
        fmt: FormatType = None,
    ) -> Optional[Translatable]:
        """Translate IDs to human-readable strings.

        For an introduction to translation, see the :ref:`translation-primer` page.

        See Also:
            🔑 This is a key event method. Exit-events are emitted on the ``ℹ️INFO``-level if the ``Translator`` is
            :attr:`online`. Enter-events are always emitted on the ``🪲DEBUG``-level. See :ref:`key-events` for details.

        Args:
            translatable: A data structure to translate.
            names: Explicit names to translate. Derive from `translatable` if ``None``. Alternatively, you may pass a
                ``dict`` on the form ``{name_in_translatable: source_to_use}``.
            ignore_names: Names **not** to translate, or a predicate ``(str) -> bool``.
            inplace: If ``True``, translate in-place and return ``None``.
            override_function: A callable ``(name, fetcher.sources, ids) -> Source | None``. See :meth:`.Mapper.apply`
                for details.
            maximal_untranslated_fraction: The maximum fraction of IDs for which translation may fail before an error is
                raised. 1=disabled. Ignored in `reverse` mode.
            reverse: If ``True``, perform translations back to IDs. Offline mode only.
            attribute: If given, translate ``translatable.attribute`` instead. If ``inplace=False``, the translated
                attribute will be assigned to `translatable` using
                ``setattr(translatable, attribute, <translated-attribute>)``.
            fmt: Format to use. If ``None``, fall back to init format.

        Returns:
            A translated copy of `translatable` if ``inplace=False``, otherwise ``None``.

        Examples:
            Manual `name-to-source <../documentation/translation-primer.html#name-to-source-mapping>`__ mapping with a
            temporary name-only :class:`.Format`.

            ..
               # Hidden setup code
               >>> translator = Translator({'animals': {'id': [2], 'name': ['Simba']}})

            >>> n2s = {'lions': 'animals', 'big_cats': 'animals'}
            >>> translator.translate({'lions': 2, 'big_cats': 2}, names=n2s, fmt="{name}")
            {'lions': 'Simba', 'big_cats': 'Simba'}

            Name mappings must be complete; any name not present in the keys will be ignored (left as-is).

        Raises:
            UntranslatableTypeError: If ``type(translatable)`` cannot be translated.
            MissingNamesError: If `names` are not given and cannot be derived from `translatable`.
            MappingError: If any required (explicitly given) names fail to map to a source.
            MappingError: If name-to-source mapping is ambiguous.
            ValueError: If `maximal_untranslated_fraction` is not a valid fraction.
            TooManyFailedTranslationsError: If translation fails for more than `maximal_untranslated_fraction` of IDs.
            ConnectionStatusError: If ``reverse=True`` while the ``Translator`` is online.
            UserMappingError: If `override_function` returns a source which is not known, and
                ``self.mapper.unknown_user_override_action != 'ignore'``.
        """  # noqa: DAR101 darglint is bugged here
        if getenv(ID_TRANSLATION_DISABLED, "").lower() == "true":
            message = "Translation aborted; ID_TRANSLATION_DISABLED is set."
            LOGGER.warning(message)
            warnings.warn(message, category=TranslationDisabledWarning, stacklevel=2)
            return None if inplace else translatable

        if fmt is not None:
            real_fmt = self._fmt
            try:
                parameters = set(signature(Translator.translate).parameters)
                parameters.remove("self")
                parameters.remove("fmt")
                kwargs = {key: value for key, value in locals().items() if key in parameters}
                self._fmt = Format.parse(fmt)
                return self.translate(**kwargs)
            finally:
                self._fmt = real_fmt

        start = perf_counter()

        key_event_level = logging.INFO if self.online else logging.DEBUG
        should_emit_key_event = LOGGER.isEnabledFor(key_event_level)
        if should_emit_key_event:
            event_key = f"{self.__class__.__name__.upper()}.TRANSLATE"

            type_name = _resolve_type_name(translatable, attribute)
            name_info = f"Derive based on type={type_name}" if names is None else repr(names)
            if ignore_names is not None:
                name_info += f", excluding those given by {ignore_names=}"

            sources = self.sources  # Ensures that the fetcher is warmed up; good for log organization.
            LOGGER.log(
                level=logging.DEBUG,
                msg=f"Begin translation of {type_name}-type data. Names to translate: {name_info}.",
                extra=dict(
                    event_key=event_key,
                    event_stage="ENTER",
                    event_title=f"{event_key}.ENTER",
                    translatable_type=type_name,
                    names=names,
                    ignore_names=tname(ignore_names, prefix_classname=True) if callable(ignore_names) else ignore_names,
                    inplace=inplace,
                    sources=sources,
                    fmt=repr(self._fmt),
                    maximal_untranslated_fraction=maximal_untranslated_fraction,
                    attribute=attribute,
                    reverse=reverse,
                    online=self.online,
                ),
            )

        if self.online and reverse:  # pragma: no cover
            raise ConnectionStatusError("Reverse translation cannot be performed online.")

        if not (0.0 <= maximal_untranslated_fraction <= 1):  # pragma: no cover
            raise ValueError(f"Argument {maximal_untranslated_fraction=} is not a valid fraction")

        if attribute:
            obj, translatable = translatable, getattr(translatable, attribute)
        else:
            obj = None

        names, override_function = _handle_input_names(names, override_function)
        translation_map, names_to_translate = self._get_updated_tmap(
            translatable,
            names,
            ignore_names=ignore_names,
            override_function=override_function,
            parent=obj if (obj is not None and self._allow_name_inheritance) else None,
        )
        if not translation_map:
            return None if inplace else translatable  # pragma: no cover

        translatable_io = resolve_io(translatable)
        if LOGGER.isEnabledFor(logging.DEBUG) or maximal_untranslated_fraction < 1.0:
            self._verify_translations(
                translatable,
                names_to_translate if names is None else names,
                translation_map,
                translatable_io,
                maximal_untranslated_fraction,
            )

        translation_map.reverse_mode = reverse
        try:
            ans = translatable_io.insert(
                translatable,
                names=names_to_translate if names is None else names,
                tmap=translation_map,
                copy=not inplace,
            )
        finally:
            translation_map.reverse_mode = False

        if attribute and not inplace and ans is not None:
            setattr(obj, attribute, ans)
            # Hacky special handling for e.g. pandas.Index
            if hasattr(ans, "name") and hasattr(translatable, "name"):  # pragma: no cover
                ans.name = translatable.name
            ans = obj

        if should_emit_key_event:
            execution_time = perf_counter() - start
            inplace_info = "Original values have been replaced" if inplace else "Returning a translated copy"

            n2s_with_none = {name: translation_map.name_to_source.get(name) for name in names_to_translate}
            LOGGER.log(
                level=key_event_level,
                msg=f"Finished translation of {type_name}-type data in {format_seconds(execution_time)}"
                f" using name-to-source mapping: {n2s_with_none}. {inplace_info} (since {inplace=}).",
                extra=dict(
                    event_key=event_key,
                    event_stage="EXIT",
                    event_title=f"{event_key}.EXIT",
                    execution_time=execution_time,
                    translatable_type=type_name,
                    names=names_to_translate,
                    name_to_source_mapping=translation_map.name_to_source,
                    inplace=inplace,
                    fmt=repr(translation_map.fmt),
                    maximal_untranslated_fraction=maximal_untranslated_fraction,
                    attribute=attribute,
                    reverse=reverse,
                    online=self.online,
                ),
            )

        self._translated_names = names_to_translate

        return ans

    def translated_names(self) -> List[NameType]:
        """Return the names that were translated by the most recent :meth:`translate`-call.

        Returns:
            Recent names translated by this ``Translator``, in **arbitrary** order.

        Raises:
            ValueError: If no names have been translated using this ``Translator``.
        """
        if self._translated_names is None:
            raise ValueError("No names have been translated using this Translator.")
        return list(self._translated_names)

    def map(  # noqa: A003
        self,
        translatable: Translatable,
        names: NameTypes[NameType] = None,
        ignore_names: Names[NameType] = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] = None,
    ) -> Optional[DirectionalMapping[NameType, SourceType]]:
        """Map names to translation sources.

        Args:
            translatable: A data structure to map names for.
            names: Explicit names to translate. Derive from `translatable` if ``None``.
            ignore_names: Names **not** to translate, or a predicate ``(str) -> bool``.
            override_function: A callable ``(name, fetcher.sources, ids) -> Source | None``. See
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
        return self._map_inner(translatable, names, ignore_names=ignore_names, override_function=override_function)

    def map_scores(
        self,
        translatable: Translatable,
        names: NameTypes[NameType] = None,
        ignore_names: Names[NameType] = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] = None,
    ) -> pd.DataFrame:
        """Returns raw match scores for name-to-source mapping. See :meth:`map` for details."""
        names_to_translate = self._resolve_names(translatable, names, ignore_names)
        return self.mapper.compute_scores(names_to_translate, self.sources, override_function=override_function)

    @property
    def sources(self) -> List[SourceType]:
        """A list of known Source names, such as ``cities`` or ``languages`` (from :attr:`fetcher` or :attr:`cache`)."""
        return list(self.placeholders)

    @property
    def placeholders(self) -> Dict[SourceType, List[str]]:
        """Placeholders for all known Source names, such as ``id`` or ``name`` (from :attr:`fetcher` or :attr:`cache`).

        These are the (possibly unmapped) placeholders that may be used for translation.

        Returns:
            A dict ``{source: [placeholders..]}``.
        """  # noqa: DAR202
        return self._fetcher.placeholders if self.online else self._cached_tmap.placeholders

    def _map_inner(
        self,
        translatable: Translatable,
        names: NameTypes[NameType] = None,
        ignore_names: Names[NameType] = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] = None,
        parent: Translatable = None,
    ) -> Optional[DirectionalMapping[NameType, SourceType]]:
        start = perf_counter()
        names_to_translate = self._resolve_names(translatable, names, ignore_names, parent)

        def format_params() -> str:
            params = []
            if ignore_names is not None:
                params.append(f"{ignore_names=}")
            if override_function is not None:
                params.append(f"{override_function=}")
            if parent is not None:
                params.append(f"parent={tname(parent)}")
            return f". Parameters: ({', '.join(params)})" if params else ""

        if names is not None and not names:
            type_name = _resolve_type_name(translatable)
            msg = f"Translation aborted; no names to translate in {type_name}{format_params()}."
            warnings.warn(msg, MappingWarning, stacklevel=2)
            LOGGER.warning(msg)
            return None

        if LOGGER.isEnabledFor(logging.DEBUG):
            event_key = f"{self.__class__.__name__.upper()}.MAP"
            type_name = _resolve_type_name(translatable)
            sources = self.sources
            LOGGER.debug(
                f"Begin name-to-source mapping of names={names_to_translate} in {type_name} against {sources=}.",
                extra=dict(
                    event_key=event_key,
                    event_stage="ENTER",
                    event_title=f"{event_key}.ENTER",
                    translatable_type=type_name,
                    values=names_to_translate,
                    candidates=sources,
                    context=None,
                ),
            )
        name_to_source = self.mapper.apply(names_to_translate, self.sources, override_function=override_function)
        if LOGGER.isEnabledFor(logging.DEBUG):
            execution_time = perf_counter() - start
            LOGGER.debug(
                f"Finished name-to-source mapping of names={names_to_translate} in {type_name} against {sources=}:"
                f" {name_to_source.left_to_right}.",
                extra=dict(
                    event_key=event_key,
                    event_stage="EXIT",
                    event_title=f"{event_key}.EXIT",
                    execution_time=execution_time,
                    translatable_type=type_name,
                    mapping=name_to_source.left_to_right,
                    context=None,
                ),
            )

        unmapped = set() if names is None else set(as_list(names)).difference(name_to_source.left)
        if unmapped or not name_to_source.left:
            tail = f"could not be mapped to sources={self.sources}{format_params()}"

            if names is None:
                derived_names = self._resolve_names(translatable, None, None, parent)
                msg = f"Translation aborted; none of the derived names {derived_names} {tail}."
                warnings.warn(msg, MappingWarning, stacklevel=2)
                LOGGER.warning(msg)
                return None
            elif unmapped:
                # Fail if any of the explicitly given names fail to map to a source.
                msg = f"Required names {unmapped} {tail}."
                LOGGER.error(msg)
                raise MappingError(msg)

        if name_to_source.cardinality.many_right:  # pragma: no cover
            for value, candidates in name_to_source.left_to_right.items():
                if len(candidates) > 1:
                    raise MappingError(
                        f"Name-to-source mapping {name_to_source.left_to_right} is ambiguous; {value} -> {candidates}."
                        f"\nHint: Choose a different cardinality such that Mapper.cardinality.many_right is False."
                    )
        return name_to_source

    def fetch(
        self,
        translatable: Translatable,
        name_to_source: DirectionalMapping[NameType, SourceType],
        data_structure_io: Type[DataStructureIO] = None,
        names: List[NameType] = None,
    ) -> TranslationMap[NameType, SourceType, IdType]:
        """Fetch translations.

        Args:
            translatable: A data structure to translate.
            name_to_source: Mappings of names in `translatable` to the known :attr:`sources`.
            data_structure_io: Static namespace used to extract IDs from `translatable`.
            names: A list of explicit names fetch translations for. Must mappable using the given `name_to_source`.

        Returns:
            A ``TranslationMap``.

        Raises:
            ConnectionStatusError: If disconnected from the fetcher, i.e. not :attr:`online`.
        """
        ids_to_fetch = self._get_ids_to_fetch(
            name_to_source,
            translatable,
            data_structure_io or resolve_io(translatable),
            names,
        )
        source_translations = self._fetch(ids_to_fetch)
        return self._to_translation_map(source_translations)

    @property
    def online(self) -> bool:
        """Return connectivity status. If ``False``, no new translations may be fetched."""
        return hasattr(self, "_fetcher")

    @property
    def fetcher(self) -> Fetcher[SourceType, IdType]:
        """Return the ``Fetcher`` instance used to retrieve translations."""
        if not self.online:
            raise ConnectionStatusError("Cannot fetch new translations.")  # pragma: no cover

        return self._fetcher

    @property
    def mapper(self) -> Mapper[NameType, SourceType, None]:
        """Return the ``Mapper`` instance used for name-to-source binding."""
        return self._mapper

    @property
    def cache(self) -> TranslationMap[NameType, SourceType, IdType]:
        """Return a ``TranslationMap`` of cached translations."""
        return self._cached_tmap

    @classmethod
    def load_persistent_instance(
        cls,
        cache_dir: PathLikeType,
        config_path: PathLikeType,
        extra_fetchers: Iterable[PathLikeType] = (),
        max_age: Union[str, pd.Timedelta, timedelta] = "12h",
        clazz: Union[str, Type["Translator[NameType, SourceType, IdType]"]] = None,
    ) -> "Translator[NameType, SourceType, IdType]":
        """Load or create a persistent :attr:`~.Fetcher.fetch_all`-instance.

        Instances are created, stored and loaded as determined by a metadata file located in the given `cache_dir`. A
        new ``Translator`` will be created if:

        * There is no `'metadata'` file, or
        * the original ``Translator`` is too old (see `max_age`), or
        * the current configuration -- as defined by ``(config_path, extra_fetchers, clazz)`` -- has changed in such a
          way that it is no longer equivalent configuration used to create the original ``Translator``. For details, see
          :class:`ConfigMetadata`.

        .. warning:: This method is **not** thread safe.

        Args:
            cache_dir: Root directory where the cached translator and associated metadata is stored.
            config_path: Path to the main TOML configuration file.
            extra_fetchers: Paths to fetching configuration TOML files. If multiple fetchers are defined, they are
                ranked by input order. If a fetcher defined in the main configuration, it will be prioritized (rank=0).
            max_age: The maximum age of the cached ``Translator`` before it must be recreated. Pass ``max_age='0d'`` to
                force recreation.
            clazz: Translator implementation to create. If a string is passed, the class is resolved using
                :func:`~rics.misc.get_by_full_name` if a string is given. Use ``cls`` if ``None``.

        Returns:
            A new or cached ``Translator`` instance with a :attr:`config_metadata` attribute.

        See Also:
             The :meth:`from_config` method, which will initialize the Translator using `path`, `extra_fetchers`, and
                `clazz` if the cached instance is outdated.
        """
        path = Path(str(config_path))
        cache_dir = Path(str(cache_dir)).expanduser().absolute()
        cache_dir.mkdir(parents=True, exist_ok=True)

        metadata_path = cache_dir.joinpath("metadata.json")
        cache_path = cache_dir.joinpath("translator.pkl")

        extra_fetcher_paths: List[str] = list(map(str, extra_fetchers))

        metadata = ConfigMetadata.from_toml_paths(
            str(path),
            extra_fetcher_paths,
            clazz=TranslatorFactory.resolve_class(clazz),
        )
        if metadata.use_cached(metadata_path, pd.Timedelta(max_age).to_pytimedelta()):
            return cls.restore(cache_path)
        else:
            ans: Translator[NameType, SourceType, IdType] = cls.from_config(path, extra_fetcher_paths, clazz)
            ans.store(path=cache_path, delete_fetcher=True)
            metadata_path.write_text(ans.config_metadata.to_json())
            return ans

    @classmethod
    def restore(cls, path: PathLikeType) -> "Translator[NameType, SourceType, IdType]":
        """Restore a serialized ``Translator``.

        Args:
            path: Path to a serialized ``Translator``.

        Returns:
            A ``Translator``.

        Raises:
            TypeError: If the object at `path` is not a ``Translator`` or a subtype thereof.

        See Also:
            The :meth:`Translator.store` method.
        """
        import pickle  # noqa: S403

        full_path = Path(str(path)).expanduser()
        with full_path.open("rb") as f:
            ans = pickle.load(f)  # noqa: S301

        if not isinstance(ans, cls):  # pragma: no cover
            raise TypeError(f"Serialized object at at '{full_path}' is a {type(ans)}, not {cls}.")

        if LOGGER.isEnabledFor(logging.DEBUG):
            extra = "" if ans._config_metadata is None else f" with {ans.config_metadata}"
            LOGGER.debug(f"Deserialized {ans}{extra}.")

        return ans

    def store(
        self,
        translatable: Translatable = None,
        names: NameTypes[NameType] = None,
        ignore_names: Names[NameType] = None,
        delete_fetcher: bool = True,
        path: PathLikeType = None,
    ) -> "Translator[NameType, SourceType, IdType]":  # noqa: DAR401  false positive
        """Retrieve and store translations in memory.

        Args:
            translatable: Data from which IDs to fetch will be extracted. Fetch all IDs if ``None``.
            names: Explicit names to translate. Derive from `translatable` if ``None``.
            ignore_names: Names **not** to translate, or a predicate ``(str) -> bool``.
            delete_fetcher: If ``True``, invoke :meth:`.Fetcher.close` and delete the fetcher after retrieving data. The
                ``Translator`` will still function, but new data cannot be retrieved.
            path: If given, serialize the ``Translator`` to disk after retrieving data.

        Returns:
            Self, for chained assignment.

        Raises:
            ForbiddenOperationError: If :meth:`.Fetcher.fetch_all` is disabled and ``translatable=None``.
            MappingError: If :meth:`map` fails (only when `translatable` is given).

        Notes:
            The ``Translator`` is guaranteed to be :func:`~rics.misc.serializable` once offline. Fetchers often
            aren't as they require things like database connections to function.

        See Also:
            The :meth:`Translator.restore` method.
        """
        start = perf_counter()
        if translatable is None:
            source_translations: SourcePlaceholderTranslations[SourceType] = self._fetch(None)
            translation_map = self._to_translation_map(source_translations)
        else:
            maybe_none, _ = self._get_updated_tmap(translatable, names, ignore_names=ignore_names, force_fetch=True)
            if maybe_none is None:
                raise MappingError("No values in the translatable were mapped. Cannot store translations.")
            translation_map = maybe_none  # mypy, would be cleaner to just use translation map..
            if LOGGER.isEnabledFor(logging.DEBUG):
                not_fetched = set(self.fetcher.sources).difference(translation_map.sources)
                LOGGER.debug(f"Available sources {not_fetched} were not fetched.")

        if delete_fetcher:  # pragma: no cover
            self.fetcher.close()
            del self._fetcher

        self._cached_tmap = translation_map

        message = f"Created {self} in {format_perf_counter(start)}."
        if path:
            import os
            import pickle  # noqa: S403

            path = Path(str(path)).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                pickle.dump(self, f)

            mb_size = os.path.getsize(path) / 2**20
            message += f" Serialized {mb_size:.2g} MiB at path='{path}'."

        LOGGER.info(message)
        return self

    def _get_updated_tmap(
        self,
        translatable: Translatable,
        names: NameTypes[NameType] = None,
        ignore_names: Names[NameType] = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] = None,
        force_fetch: bool = False,
        parent: Translatable = None,
    ) -> Tuple[Optional[TranslationMap[NameType, SourceType, IdType]], List[NameType]]:
        """Get an updated translation map.  # noqa

        Setting ``force_fetch=True`` will ignore the cached translation if there is one.

        Steps:
            1. Resolve which data structure IO to use, fail if not found.
            2. Resolve name-to-source mappings. If none are found, return ``None``.
            3. Create a new translation map, or update the cached one.

        See the :meth:`translate`-method for more detailed documentation.
        """
        translatable_io = resolve_io(translatable)  # Fail fast if untranslatable type

        names, override_function = _handle_input_names(names, override_function)
        name_to_source = self._map_inner(translatable, names, ignore_names, override_function, parent)
        if name_to_source is None:
            # Nothing to translate.
            return None, []  # pragma: no cover

        translation_map = (
            self.fetch(translatable, name_to_source, translatable_io, names)
            if force_fetch or not self.cache
            else self.cache
        )

        translation_map.enable_uuid_heuristics = self._enable_uuid_heuristics
        translation_map.fmt = self._fmt
        n2s = name_to_source.flatten()
        translation_map.name_to_source = n2s  # Update
        return translation_map, list(n2s)

    def _get_ids_to_fetch(
        self,
        name_to_source: DirectionalMapping[NameType, SourceType],
        translatable: Translatable,
        dio: Type[DataStructureIO],
        names: Optional[List[NameType]],
    ) -> List[IdsToFetch[SourceType, IdType]]:
        # Aggregate and remove duplicates.
        source_to_ids: Dict[SourceType, Set[IdType]] = {source: set() for source in name_to_source.right}
        n2s = name_to_source.flatten()  # Will fail if sources are ambiguous.

        float_names: List[NameType] = []
        num_coerced = 0
        for name, ids in dio.extract(translatable, list(n2s) if names is None else names).items():
            if len(ids) == 0:
                continue

            if isinstance(ids[0], float):
                float_names.append(name)
                # Float IDs aren't officially supported, but is common when using Pandas since int types cannot be NaN.
                # This is sometimes a problem for the built-in set (see https://github.com/numpy/numpy/issues/9358), and
                # for several database drivers.
                arr = numpy.unique(ids)
                keep_mask = ~numpy.isnan(arr)
                num_coerced += keep_mask.sum()  # Somewhat inaccurate; includes repeat IDs from other names
                source_to_ids[n2s[name]].update(arr[keep_mask].astype(int, copy=False))
            else:
                if self._enable_uuid_heuristics:
                    ids = _uuid_utils.try_cast_many(ids)

                source_to_ids[n2s[name]].update(ids)  # type: ignore[arg-type]

        if num_coerced > 100 and self.online:  # pragma: no cover
            warnings.warn(
                f"To ensure proper fetcher operation, {num_coerced} float-type IDs have been coerced to integers. "
                f"Enforcing supported data types for IDs (str and int) in your {tname(translatable)}-data may improve "
                f"performance. Affected names ({len(float_names)}): {float_names}."
                "\nHint: Going offline will suppress this warning.",
                stacklevel=3,
            )

        return [IdsToFetch(source, ids) for source, ids in source_to_ids.items()]

    def _fetch(
        self, ids_to_fetch: Optional[List[IdsToFetch[SourceType, IdType]]]
    ) -> SourcePlaceholderTranslations[SourceType]:
        placeholders = self._fmt.placeholders
        required = self._fmt.required_placeholders

        if self._default_fmt and ID in self._default_fmt.placeholders and ID not in placeholders:
            # Ensure that default translations can always use the ID
            placeholders = placeholders + (ID,)
            required = required + (ID,)

        return (
            self.fetcher.fetch_all(placeholders, required)
            if ids_to_fetch is None
            else self.fetcher.fetch(ids_to_fetch, placeholders, required)
        )

    def _to_translation_map(
        self, source_translations: SourcePlaceholderTranslations[SourceType]
    ) -> TranslationMap[NameType, SourceType, IdType]:
        return TranslationMap(
            source_translations,
            fmt=self._fmt,
            default_fmt=self._default_fmt,
            default_fmt_placeholders=self._default_fmt_placeholders,
            enable_uuid_heuristics=self._enable_uuid_heuristics,
        )

    @staticmethod
    def _verify_translations(
        translatable: Translatable,
        names_to_translate: List[NameType],
        translation_map: TranslationMap[NameType, SourceType, IdType],
        translatable_io: Type[DataStructureIO],
        maximal_untranslated_fraction: float,
    ) -> None:
        copied_map = translation_map.copy()
        # TODO: Remove the ignores when https://github.com/python/mypy/issues/3004 (5+ years old..) is fixed.
        copied_map.fmt = "found"  # type: ignore
        copied_map.default_fmt = ""  # type: ignore
        ans = translatable_io.insert(translatable, names=names_to_translate, tmap=copied_map, copy=True)
        extracted = translatable_io.extract(ans, names=names_to_translate)

        total_untranslated = 0
        for name, translations in extracted.items():
            num = sum(t == "" for t in translations)
            total_untranslated += num

            if num == 0:
                continue

            frac = num / len(translations)
            if LOGGER.isEnabledFor(logging.DEBUG) or frac > maximal_untranslated_fraction:
                source = translation_map.name_to_source[name]
                msg = f"Failed to translate {num}/{len(translations)} ({frac:.3%}) of IDs for {name=} using {source=}."
                LOGGER.debug(msg)
                if frac > maximal_untranslated_fraction:
                    raise TooManyFailedTranslationsError(
                        msg + f" Limit: maximal_untranslated_fraction={maximal_untranslated_fraction:.3%}"
                    )

        if total_untranslated or LOGGER.isEnabledFor(logging.DEBUG):
            n_ids = sum(map(len, extracted.values()))
            LOGGER.log(
                logging.WARNING if maximal_untranslated_fraction < 1 else logging.DEBUG,
                f"Failed to translate {total_untranslated}/{n_ids} ({total_untranslated / n_ids:.3%}) "
                f"of IDs extracted from {len(extracted)} different names.",
            )

    def __repr__(self) -> str:
        more = f"fetcher={self.fetcher}" if self.online else f"cache={self.cache}"

        online = self.online
        return f"{tname(self)}({online=}: {more})"

    def _resolve_names(
        self,
        translatable: Translatable,
        names: NameTypes[NameType] = None,
        ignored_names: Names[NameType] = None,
        parent: Any = None,
    ) -> List[NameType]:
        if names is None:
            names = resolve_io(translatable).names(translatable)
            if names is None and parent is not None and self._allow_name_inheritance:
                try:
                    names = resolve_io(parent).names(parent)
                except UntranslatableTypeError:
                    LOGGER.debug(f"Cannot use {tname(parent)!r}-type parent to derive names; not a translatable type.")

            if names is None:
                raise MissingNamesError(
                    f"Failed to derive names for {tname(translatable)!r}-type data."
                    "\nHint: Use the 'names'-argument to specify names to translate."
                )
            if LOGGER.isEnabledFor(logging.DEBUG):
                LOGGER.debug(f"Name resolution complete. Found {names=} for {tname(translatable)!r}-type data.")

            if ignored_names is not None:
                predicate = ignored_names if callable(ignored_names) else set(as_list(ignored_names)).__contains__
                names = [name for name in names if not predicate(name)]
        else:
            if ignored_names is not None:
                raise ValueError(f"Required {names=} cannot be used with {ignored_names=}.")
            names = as_list(names)

        return names


def _handle_default(
    fmt: Format,
    default_fmt: Optional[FormatType],
    default_fmt_placeholders: Optional[MakeType[SourceType, str, Any]],
) -> Tuple[Optional[InheritedKeysDict[SourceType, str, Any]], Optional[Format]]:  # pragma: no cover
    if default_fmt is None and default_fmt_placeholders is None:
        return None, None

    dt: Optional[InheritedKeysDict[SourceType, str, Any]] = None

    if isinstance(default_fmt_placeholders, InheritedKeysDict):
        dt = default_fmt_placeholders
    elif isinstance(default_fmt_placeholders, dict):
        dt = InheritedKeysDict.make(default_fmt_placeholders)

    dfmt: Optional[Format]
    if default_fmt is None:
        dfmt = None
    elif isinstance(default_fmt, str):
        dfmt = Format(default_fmt)
    else:
        dfmt = default_fmt

    if dt is not None and dfmt is None:
        # Force a default format if default translations are given
        dfmt = fmt

    if dfmt is not None:
        dt = dt or InheritedKeysDict()

    return dt, dfmt


def _resolve_type_name(translatable: Translatable, attribute: str = None) -> str:
    type_name = tname(translatable, prefix_classname=True)
    if attribute:
        real_type_name = tname(getattr(translatable, attribute), prefix_classname=True)
        type_name = f"{real_type_name!r} (from {type_name}.{attribute})"
    else:
        type_name = repr(type_name)
    return type_name


def _handle_input_names(
    names: Optional[Union[NameTypes[NameType], NameToSource[NameType, SourceType]]],
    override_function: Optional[UserOverrideFunction[NameType, SourceType, None]],
) -> Tuple[Optional[List[NameType]], Optional[UserOverrideFunction[NameType, SourceType, None]]]:
    if names is None:
        return None, override_function

    if isinstance(names, dict):
        if override_function is not None:
            raise ValueError(f"Dict-type {names=} cannot be combined with {override_function=}.")

        override_function = _UserDefinedNameToSourceMapping(dict(names))

    return as_list(names), override_function


class _UserDefinedNameToSourceMapping:
    def __init__(self, name_to_source: NameToSource[NameType, SourceType]) -> None:
        for name, source in name_to_source.items():
            if source is None:
                raise ValueError(
                    f"Bad name-to-source mapping: {name!r} -> {source!r}."
                    f"\nHint: Remove None-values from names={name_to_source}."
                )
        self._name_to_source = name_to_source

    def __call__(self, name: NameType, sources: Set[SourceType], context: None) -> Optional[SourceType]:
        return self._name_to_source.get(name)

    def __repr__(self) -> str:
        return f"UserArgument(names={self._name_to_source})"
