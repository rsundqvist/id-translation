import logging
import threading
from abc import abstractmethod
from collections.abc import Iterable, Iterator, Mapping, MutableMapping, Sequence
from contextlib import contextmanager
from copy import deepcopy
from time import perf_counter
from types import MappingProxyType
from typing import Any, Generic, Self, TypedDict, final

from rics.collections.dicts import InheritedKeysDict, reverse_dict
from rics.misc import tname
from rics.strings import format_seconds as fmt_sec

from .. import logging as _logging
from .._utils.emit_warning import emit_warning
from ..mapping import HeuristicScore, Mapper
from ..mapping.exceptions import MappingWarning
from ..mapping.score_functions import modified_hamming
from ..offline.types import (
    PlaceholderAttributes,
    PlaceholdersTuple,
    PlaceholderTranslations,
    SourcePlaceholderTranslations,
)
from ..types import ID, IdType, SourceType
from . import exceptions
from ._cache_access import CacheAccess
from ._cache_coordinator import CacheCoordinator
from ._fetcher import Fetcher
from .types import FetchInstruction, IdsToFetch


class AbstractFetcherParams(TypedDict, Generic[SourceType, IdType], total=False):
    """Keyword arguments for the :class:`~id_translation.fetching.AbstractFetcher` base class."""

    mapper: Mapper[str, str, SourceType] | None
    allow_fetch_all: bool
    selective_fetch_all: bool
    identifiers: Sequence[str] | None
    optional: bool
    cache_access: CacheAccess[SourceType, IdType] | None


class AbstractFetcher(Fetcher[SourceType, IdType]):
    """Common base class.

    The ``AbstractFetcher`` implements common utility for use by more specialized fetchers. It provides functions such
    as :ref:`mapping <placeholder-mapping>` and validation of the relevant
    :attr:`~id_translation.offline.Format.placeholders`. It also adds extensive logging and scaffolding for the
    :ref:`caching <caching_example>` API, as well as a handful of other features.

    Abstract methods:
        * :meth:`~id_translation.fetching.AbstractFetcher._initialize_sources`: Source discovery. The result is kept once
          it returns.
        * :meth:`~id_translation.fetching.AbstractFetcher.fetch_translations`: Retrieve translation data based on a
          :class:`~id_translation.fetching.types.FetchInstruction`.

    All bundled fetchers (except the :class:`~id_translation.fetching.MultiFetcher`) inherit from this class.

    Args:
        mapper: A :class:`~id_translation.mapping.Mapper` instance used to adapt placeholder names in sources to wanted
            names, i.e. the names of the placeholders that are in the translation
            :class:`~id_translation.offline.Format` being used.
        allow_fetch_all: If ``False``, an error will be raised when
            :meth:`~id_translation.fetching.AbstractFetcher.fetch_all` is called.
        selective_fetch_all: If ``True``, fetch only from those :attr:`~id_translation.types.HasSources.sources` that
            contain the required :attr:`~id_translation.types.HasSources.placeholders` (after mapping). May reduce the
            number of sources retrieved.
        identifiers: A collection of hierarchical identifiers. One ending with ``.toml`` becomes the
            :attr:`~id_translation.fetching.AbstractFetcher.config_file`, which labels this fetcher's log records.
        optional: If ``True``, this fetcher may be discarded if source/placeholder-enumeration fails in multi-fetcher
            mode. Optional fetchers should not raise before ``_initialize_sources()`` is called.
        cache_access: A :class:`~id_translation.fetching.CacheAccess` instance. Defaults to a NOOP-implementation (i.e.
            always fetch new data).

    See Also:
        See the :ref:`🚀 examples page <orm_example>` for an implementation example.
    """

    def __init__(
        self,
        *,
        mapper: Mapper[str, str, SourceType] | None = None,
        allow_fetch_all: bool = True,
        selective_fetch_all: bool = True,
        identifiers: Sequence[str] | None = None,
        optional: bool = False,
        cache_access: CacheAccess[SourceType, IdType] | None = None,
    ) -> None:
        self._mapper: Mapper[str, str, SourceType] = mapper or Mapper(**self._default_mapper_kwargs())
        if self._mapper.on_unmapped == "raise":
            emit_warning(
                "Using on_unmapped='raise' will treat optional placeholders as "
                "required placeholders during normal operation.",
                category=MappingWarning,
            )

        self._allow_fetch_all: bool = allow_fetch_all
        self._selective_fetch_all = selective_fetch_all

        identifiers = () if identifiers is None else (*identifiers,)
        config_file = self._find_config_file(identifiers)
        self._identifiers: tuple[str, ...] = identifiers
        self._config_file = config_file

        self.logger = logging.getLogger(__package__).getChild(type(self).__name__)
        self._mapper.logger = _ExtraLoggerAdapter(self.logger.logger.getChild("map"), self._log_extra())
        self._optional = optional

        self._placeholders: dict[SourceType, list[str]] | None = None
        self._discovered_id_columns: dict[SourceType, str | None] | None = None

        self._active_operations: dict[str, int] = {}

        if cache_access is not None:
            cache_access.set_parent(self)
        self._cache: CacheCoordinator[SourceType, IdType] = CacheCoordinator(self, cache_access)

    @final  # Prevent accidental overriding
    def initialize_sources(self, task_id: int | None = None) -> None:
        if self._placeholders is not None:
            return

        start = perf_counter()
        if task_id is None:
            task_id = _logging.generate_task_id(start)

        logger = self.logger
        if _logging.ENABLE_VERBOSE_LOGGING and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Begin initialization of '{self._cls_name()}' at {hex(id(self))}.",
                extra=dict(
                    task_id=task_id,
                    event_key=_logging.get_event_key(self.initialize_sources, "enter"),
                ),
            )

        with self._detect_concurrent_access("initialize_sources"):
            self._discovered_id_columns = {}
            try:
                placeholders = self._initialize_sources(task_id)
                if placeholders is None:
                    raise exceptions.ImplementationError(
                        f"{self._cls_name()}._initialize_sources() returned None;"
                        " it must return a dict {source: [placeholder, ...]}."
                    )
                self._verify_id_columns(placeholders, task_id)
                self._verify_overrides(placeholders)
            finally:
                self._discovered_id_columns = None
            self._placeholders = placeholders

        if logger.isEnabledFor(logging.INFO):
            seconds = perf_counter() - start
            logger.info(
                f"Finished initialization of '{self._cls_name()}' in {fmt_sec(seconds)}: {self}",
                extra=dict(
                    task_id=task_id,
                    event_key=_logging.get_event_key(self.initialize_sources, "exit"),
                    seconds=seconds,
                ),
            )

    @abstractmethod
    def _initialize_sources(self, task_id: int) -> dict[SourceType, list[str]]:
        """Perform a full (re) discovery of sources and placeholders.

        The actual names used by the underlying system (e.g. a database) should be returned. The required mapping
        operations are performed automatically when :meth:`~id_translation.fetching.AbstractFetcher.fetch_translations`
        is invoked. The :meth:`~id_translation.fetching.AbstractFetcher.id_column` method may be used by implementations
        that must resolve a primary ID column as part of the initialization process.

        .. important::

           Runtime errors should be raised here, **not** in the ``__init__`` method.

        If discovery fails (e.g. because the target database is not accessible), the exception should be raised here.
        The :class:`~id_translation.fetching.MultiFetcher` will suppress exceptions [#f1]_ raised by
        :attr:`~id_translation.fetching.AbstractFetcher.optional` children, except configuration errors (a
        :class:`~id_translation.exceptions.ConfigurationError`, or a source missing a required placeholder).

        Every returned source must have an ID column, or
        :meth:`~id_translation.fetching.AbstractFetcher.initialize_sources` raises. Leave out sources that should be
        skipped, and do so before calling :meth:`~id_translation.fetching.AbstractFetcher.id_column`: an override
        naming a column that the source lacks raises rather than returning ``None``.

        Args:
            task_id: Used for logging.

        Returns:
            A dict ``{source: [placeholder_names, ...]}``.

        See Also:
            The :envvar:`ID_TRANSLATION_SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS` variable.

        .. rubric:: Footnotes

        .. [#f1] The log level is configurable using the `fetcher_discarded_log_level` parameter.
        """

    @final
    @property
    def selective_fetch_all(self) -> bool:
        """If set, reduce the amount of data fetched by :meth:`~id_translation.fetching.AbstractFetcher.fetch_all`."""
        return self._selective_fetch_all

    @final
    @property
    def placeholders(self) -> Mapping[SourceType, Sequence[str]]:
        if self._placeholders is None:
            self.initialize_sources()
            return self.placeholders

        return MappingProxyType(self._placeholders)

    @final
    @property
    def sources(self) -> list[SourceType]:
        return list(self.placeholders)

    @final
    @property
    def identifiers(self) -> tuple[str, ...]:
        """A collection of hierarchical identifiers for this fetcher."""
        return self._identifiers

    @final
    @property
    def config_file(self) -> str | None:
        """The TOML file this fetcher was declared in, or ``None`` if it wasn't built from one.

        Derived from :attr:`identifiers`; ``None`` unless one of them ends with ``.toml``.
        """
        return self._config_file

    def map_placeholders(
        self,
        source: SourceType,
        placeholders: Iterable[str],
        *,
        candidates: Iterable[str] | None = None,
        task_id: int | None = None,
    ) -> dict[str, str | None]:
        """Map `placeholder` names to the actual names seen in `source`.

        This method calls ``Mapper.apply(values=placeholders, candidates=candidates, context=source)`` using the local
        :attr:`AbstractFetcher.mapper <id_translation.fetching.AbstractFetcher.mapper>` instance.

        Args:
            source: The source to map placeholders for.
            placeholders: Desired :attr:`~id_translation.offline.Format.placeholders`.
            candidates: A subset of candidates (placeholder names) in `source` to map with `placeholders`.
            task_id: Used for logging.

        Returns:
            A dict ``{wanted_placeholder_name: actual_placeholder_name_in_source}``, where
            `actual_placeholder_name_in_source` will be ``None`` if the wanted placeholder could not be mapped to any of
            the candidates available for the source.

        Raises:
            ~id_translation.fetching.exceptions.UnknownSourceError: If `source` is not in
                :attr:`~id_translation.fetching.AbstractFetcher.sources`.

        See Also:
            🔑 This is a key event method. See :ref:`key-events` for details.
        """
        return self._map_placeholders(source, placeholders, candidates=candidates, task_id=task_id, mapper=self.mapper)

    def _map_placeholders(
        self,
        source: SourceType,
        placeholders: Iterable[str],
        *,
        candidates: Iterable[str] | None,
        task_id: int | None,
        mapper: Mapper[str, str, SourceType],
    ) -> dict[str, str | None]:
        start = perf_counter()

        if self._placeholders is not None and source not in self._placeholders:
            # Check the underlying attribute to avoid infinite recursion in _initialize_sources()-implementations that
            # call this method. This is typically done indirectly via id_column(), which requires explicit candidates.
            raise exceptions.UnknownSourceError.for_sources({source}, sources=self.sources)
        if candidates is None:
            # May lead to infinite recursion if _initialize_sources() calls map_placeholders(candidates=None).
            candidates = self.placeholders[source]

        candidates = set(candidates)
        placeholders = set(placeholders)

        logger = self.logger
        emit_key_event = self._placeholders or (_logging.ENABLE_VERBOSE_LOGGING and logger.isEnabledFor(logging.DEBUG))
        if emit_key_event:
            logger.debug(
                f"Begin mapping of wanted {placeholders=} to actual placeholders={candidates} for {source=}.",
                extra=dict(
                    task_id=task_id,
                    event_key=_logging.get_event_key(self.map_placeholders, "enter"),
                    values=list(placeholders),
                    candidates=list(candidates),
                    context=source,
                ),
            )

        dm = mapper.apply(placeholders, candidates, context=source, task_id=task_id)

        ans: dict[str, str | None] = dm.flatten()  # type: ignore[assignment]
        for not_mapped in placeholders.difference(ans):
            ans[not_mapped] = None

        if emit_key_event:
            seconds = perf_counter() - start
            logger.debug(
                f"Finished placeholder mapping for {source=}: {ans}.",
                extra=dict(
                    task_id=task_id,
                    event_key=_logging.get_event_key(self.map_placeholders, "exit"),
                    seconds=seconds,
                    mapping=ans,
                    context=source,
                ),
            )

        return ans

    def id_column(
        self,
        source: SourceType,
        *,
        candidates: Iterable[str],
        task_id: int | None = None,
    ) -> str | None:
        """Return the ID column for `source`.

        Args:
            source: The source to map the ``id`` placeholder for.
            candidates: Placeholder names that `source` has.
            task_id: Used for logging.

        Returns:
            The name in `candidates` that ``id`` maps to, or ``None`` if it does not map (e.g. `candidates` is empty).

        Raises:
            ~id_translation.fetching.exceptions.UnknownIdPlaceholderError: If ``id`` maps to a name that is not in
                `candidates`, e.g. because of a bad override.
        """
        candidates = tuple(candidates)
        if not candidates:
            id_column = None
        else:
            id_column = self.map_placeholders(source, [ID], candidates=candidates, task_id=task_id)[ID]
        if id_column is not None and id_column not in candidates:
            raise exceptions.UnknownIdPlaceholderError.for_placeholders(
                id_column,
                placeholders=candidates,
                source=source,
                caller=self,
                hints=f"The override {ID!r} -> {id_column!r} names a placeholder that {source!r} does not have.",
            )

        if self._discovered_id_columns is not None:
            self._discovered_id_columns[source] = id_column
        return id_column

    def _verify_id_columns(self, placeholders: dict[SourceType, list[str]], task_id: int) -> None:
        discovered = self._discovered_id_columns
        assert discovered is not None, "bad internal state"  # noqa: S101

        for source, candidates in placeholders.items():
            if source in discovered:
                id_column = discovered[source]
            else:
                id_column = self.id_column(source, candidates=candidates, task_id=task_id)

            if id_column is None:
                raise exceptions.UnknownPlaceholderError.for_placeholders(
                    ID,
                    placeholders=candidates,
                    source=source,
                    caller=self,
                    hints=self._missing_id_column_hint(source),
                )

    def _verify_overrides(self, placeholders: dict[SourceType, list[str]]) -> None:
        """Raise for an override that names a placeholder its source lacks, or that no source has if it is shared."""
        mapper = self.mapper
        shared_misses: dict[tuple[str, str], list[SourceType]] = {}
        for source, candidates in placeholders.items():
            overrides = mapper._get_context_overrides(source)
            blocked = self._blocked(source, overrides)
            # The ID column is checked by id_column(), which raises for shared overrides as well.
            misses = {v: c for v, c in overrides.items() if v != ID and v not in blocked and c not in candidates}
            if not misses:
                continue

            shared = mapper._get_shared_overrides(source)
            if own := {v: c for v, c in misses.items() if v not in shared}:
                raise exceptions.UnknownPlaceholderError.for_placeholders(
                    sorted(set(own.values())),
                    placeholders=candidates,
                    source=source,
                    caller=self,
                    hints=f"The overrides {own} for {source!r} name placeholders that it does not have. Correct the"
                    " column names, or remove the overrides.",
                )
            for v, c in misses.items():
                shared_misses.setdefault((v, c), []).append(source)

        # A shared override that some sources satisfy is how one table serves sources with different columns.
        for (value, candidate), sources in shared_misses.items():
            if len(sources) == len(placeholders):
                raise exceptions.UnknownPlaceholderError.for_placeholders(
                    candidate,
                    placeholders=placeholders[sources[0]],
                    source=sources[0],
                    caller=self,
                    hints=f"The shared override {value!r} -> {candidate!r} names a placeholder that no source has.",
                )

    def _blocked(self, source: SourceType, names: Iterable[str]) -> set[str]:
        """Return the `names` that overrides to ``'_'`` block for `source`.

        A fetcher may return blocked columns anyway, e.g. ``MemoryFetcher(return_all=True)``. They are never shown.
        """
        return self.mapper._blocked(names, source)

    def _missing_id_column_hint(self, source: SourceType) -> str:
        if self._blocked(source, [ID]):
            return f"An override to '_' blocks the ID column of {source!r}, but every source needs one."
        hint = f"Rename the ID column of {source!r} to {ID!r}, or map {ID!r} to it with an override."
        if not type(self).__module__.startswith("id_translation."):  # Implementer-side fix; bundled fetchers can't.
            hint += f" If {source!r} has no ID column, leave it out of {type(self).__name__}._initialize_sources()."
        if not self.mapper._apply_filters(ID, [ID], source, {}, task_id=None):  # E.g. filter_sources(), on purpose.
            hint = f"A filter rejects the ID column of {source!r}, but every source needs one."
        return hint

    @property
    def mapper(self) -> Mapper[str, str, SourceType]:
        """Return the ``Mapper`` instance used for placeholder name mapping."""
        return self._mapper

    @property
    def cache_access(self) -> CacheAccess[SourceType, IdType]:
        """Return the :class:`~id_translation.fetching.CacheAccess` for this fetcher.

        Raises:
            ~id_translation.fetching.exceptions.CacheAccessNotAvailableError: If this fetcher has no cache configured.
        """
        return self._cache.cache_access

    @property
    def allow_fetch_all(self) -> bool:
        return self._allow_fetch_all

    @property
    def logger(self) -> logging.LoggerAdapter[logging.Logger]:
        """The logger used by this instance.

        Every record logged through it carries ``fetcher_class`` and ``fetcher_config_file`` attributes naming this
        instance. The underlying ``Logger`` is ``id_translation.fetching.<class name>``; configure handlers and levels
        there, or on ``id_translation.fetching`` for all fetchers.

        Assigning a ``Logger`` wraps it in the same way. An assigned ``LoggerAdapter`` is used as-is, without the
        attributes.
        """
        return self._logger

    @logger.setter
    def logger(self, logger: logging.Logger | logging.LoggerAdapter[logging.Logger]) -> None:
        if isinstance(logger, logging.LoggerAdapter):
            self._logger = logger
        else:
            self._logger = _ExtraLoggerAdapter(logger, self._log_extra())

    def _log_extra(self) -> dict[str, str | None]:
        return {"fetcher_class": self._cls_name(), "fetcher_config_file": self._config_file}

    @property
    def optional(self) -> bool:
        return self._optional

    def fetch(
        self,
        ids_to_fetch: Iterable[IdsToFetch[SourceType, IdType]],
        placeholders: Iterable[str] = (),
        *,
        required: Iterable[str] = (),
        placeholder_attributes: PlaceholderAttributes | None = None,
        task_id: int | None = None,
        enable_uuid_heuristics: bool = False,
    ) -> SourcePlaceholderTranslations[SourceType]:
        start = perf_counter()
        if task_id is None:
            task_id = _logging.generate_task_id(start)
        self.initialize_sources(task_id)  # Before any source lookup: an unknown one must raise UnknownSourceError.

        placeholders = tuple(placeholders)
        required_placeholders = set(required)
        ids_to_fetch = tuple(ids_to_fetch)
        if len(sources := [itf.source for itf in ids_to_fetch]) != len(set(sources)):
            repeated = sorted({source for source in sources if sources.count(source) > 1}, key=str)
            raise ValueError(f"Repeated sources in ids_to_fetch: {repeated}. Merge the IDs of each source into one.")

        logger = self.logger
        if logger.isEnabledFor(logging.DEBUG):
            num_ids = {itf.source: len(itf.ids) for itf in ids_to_fetch}
            logger.debug(
                f"Begin fetching {placeholders=} for {sum(num_ids.values())} IDs from {len(num_ids)} sources: {num_ids}.",
                extra=dict(
                    task_id=task_id,
                    event_key=_logging.get_event_key(self.fetch, "enter"),
                    placeholders=placeholders,
                    required_placeholders=tuple(required_placeholders),
                    placeholder_attributes={p: sorted(attrs) for p, attrs in placeholder_attributes.items()}
                    if placeholder_attributes
                    else None,
                    num_ids=num_ids,
                    fetch_all=False,
                ),
            )

        rv = {
            itf.source: self._fetch_translations(
                itf.source,
                placeholders,
                required_placeholders=required_placeholders,
                placeholder_attributes=placeholder_attributes,
                ids=itf.ids,
                task_id=task_id,
                enable_uuid_heuristics=enable_uuid_heuristics,
                mapper=self._mapper,
            )
            for itf in ids_to_fetch
        }

        if logger.isEnabledFor(logging.INFO):
            seconds = perf_counter() - start

            num_ids = {itf.source: len(itf.ids) for itf in ids_to_fetch}
            placeholders_returned = {source: len(pht.placeholders) for source, pht in rv.items()}
            pretty = self._format_fetch_result(rv, num_ids)

            logger.info(
                f"Finished fetching from {len(rv)} sources in {fmt_sec(seconds)}: {pretty}.",
                extra=dict(
                    task_id=task_id,
                    event_key=_logging.get_event_key(self.fetch, "exit"),
                    seconds=seconds,
                    sources=[*rv],
                    placeholders_returned=placeholders_returned,
                    num_ids=num_ids,
                    num_ids_returned={source: len(pht.records) for source, pht in rv.items()},
                    fetch_all=False,
                ),
            )

        return rv

    def fetch_all(
        self,
        placeholders: Iterable[str] = (),
        *,
        required: Iterable[str] = (),
        placeholder_attributes: PlaceholderAttributes | None = None,
        sources: set[SourceType] | None = None,
        task_id: int | None = None,
        enable_uuid_heuristics: bool = False,
    ) -> SourcePlaceholderTranslations[SourceType]:
        start = perf_counter()
        if task_id is None:
            task_id = _logging.generate_task_id()

        if not self._allow_fetch_all:
            raise exceptions.ForbiddenOperationError.for_operation("FETCH_ALL", fetcher_class=self._cls_name())

        self.initialize_sources(task_id)
        if sources is not None and (unknown := set(sources).difference(self.sources)):
            raise exceptions.UnknownSourceError.for_sources(unknown, sources=self.sources)

        placeholders = tuple(placeholders)
        required_placeholders = set(required)

        logger = self.logger
        if logger.isEnabledFor(logging.DEBUG):
            wanted = self.sources if sources is None else list(sources)
            logger.debug(
                f"Begin fetching all IDs for {placeholders=} for {len(wanted)}/{len(self.sources)}: {wanted}.",
                extra=dict(
                    task_id=task_id,
                    event_key=_logging.get_event_key(self.fetch_all, "enter"),
                    placeholders=placeholders,
                    required_placeholders=tuple(required_placeholders),
                    placeholder_attributes={p: sorted(attrs) for p, attrs in placeholder_attributes.items()}
                    if placeholder_attributes
                    else None,
                    wanted_sources=wanted,
                    num_ids=None,
                    fetch_all=True,
                ),
            )

        rv = self._fetch_all(
            tuple(placeholders),
            required_placeholders=set(required),
            placeholder_attributes=placeholder_attributes,
            wanted_sources=sources,
            task_id=task_id,
            enable_uuid_heuristics=enable_uuid_heuristics,
            mapper=self._fetch_all_mapper(),
        )

        if logger.isEnabledFor(logging.INFO):
            seconds = perf_counter() - start

            pretty = self._format_fetch_result(rv, None)
            logger.info(
                f"Finished fetching all IDs from {len(self.sources) if sources is None else len(sources)}/"
                f"{len(self.sources)} sources in {fmt_sec(seconds)}: {pretty}.",
                extra=dict(
                    task_id=task_id,
                    event_key=_logging.get_event_key(self.fetch_all, "exit"),
                    seconds=seconds,
                    sources=[*rv],
                    placeholders_returned={source: len(pht.placeholders) for source, pht in rv.items()},
                    num_ids=None,
                    num_ids_returned={source: len(pht.records) for source, pht in rv.items()},
                    fetch_all=True,
                ),
            )

        return rv

    def _fetch_all(
        self,
        placeholders: PlaceholdersTuple,
        *,
        required_placeholders: set[str],
        placeholder_attributes: PlaceholderAttributes | None,
        wanted_sources: set[SourceType] | None,
        task_id: int,
        enable_uuid_heuristics: bool,
        mapper: Mapper[str, str, SourceType],
    ) -> SourcePlaceholderTranslations[SourceType]:
        if wanted_sources is None:
            wanted_sources = {*self.sources}

        if self._selective_fetch_all:
            # There's nothing stopping us from doing this for regular fetching. But we assume that then the user wants
            # fetching to fail if explicit IDs can't be translated as specified.
            sources = [
                source
                for source in wanted_sources
                if required_placeholders.issubset(
                    self._wanted_to_actual(source, required_placeholders, task_id, mapper=mapper)[0]
                )
            ]

            if discarded := wanted_sources.difference(sources):
                self.logger.info(
                    f"Ignoring {len(discarded)} sources {discarded} since required "
                    f"placeholders {sorted(required_placeholders)} could not be mapped by {self}.",
                    extra={"task_id": task_id},
                )
        else:
            sources = [*wanted_sources]

        source_translations = {}
        for source in sources:
            translations = self._fetch_translations(
                source,
                placeholders or (*self.placeholders[source],),
                required_placeholders=required_placeholders,
                placeholder_attributes=placeholder_attributes,
                task_id=task_id,
                enable_uuid_heuristics=enable_uuid_heuristics,
                mapper=mapper,
            )
            source_translations[source] = translations

        return source_translations

    @contextmanager
    def _detect_concurrent_access(self, operation: str) -> Iterator[None]:
        current = threading.get_ident()

        contender = self._active_operations.get(operation)
        if contender is not None and contender != current:
            emit_warning(exceptions.ConcurrentOperationWarning.for_operation(operation, fetcher_class=self._cls_name()))

        self._active_operations[operation] = current
        try:
            yield
        finally:
            self._active_operations.pop(operation, None)

    def _fetch_all_mapper(self) -> Mapper[str, str, SourceType]:
        """The mapper for ``fetch_all``: one that ignores unmapped placeholders when sources may be skipped.

        Passed down explicitly, never set on the instance, which other threads share.
        """
        on_unmapped = "ignore"
        selective_fetch_all = self._selective_fetch_all
        if not (selective_fetch_all and self._mapper.on_unmapped != on_unmapped):
            return self._mapper

        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(
                f"Using Mapper.{on_unmapped=} for this fetch_all-operation, since {selective_fetch_all=}."
            )
        return self._mapper.copy(on_unmapped=on_unmapped)

    @abstractmethod
    def fetch_translations(self, instr: FetchInstruction[SourceType, IdType]) -> PlaceholderTranslations[SourceType]:
        """Retrieve placeholder translations from the source.

        The :class:`~id_translation.fetching.types.FetchInstruction` will use the names returned by
        :meth:`~id_translation.fetching.AbstractFetcher._initialize_sources`; the ``AbstractFetcher`` is responsible for
        mapping in both directions. After :meth:`CacheAccess.load <id_translation.fetching.CacheAccess.load>` returns
        translations, this method is **not** called; after a :class:`~id_translation.fetching.types.PartialCacheHit`,
        it is called for the IDs the hit did not cover.

        .. note::

           Within one fetch, this method is called once per source, one source at a time. Concurrent translations
           may call it from several threads at once.

        If the :attr:`IDs <id_translation.fetching.types.FetchInstruction.ids>` of the instruction are ``None``, the
        fetcher should retrieve data for as many IDs as possible. Use
        :attr:`~id_translation.fetching.AbstractFetcher.allow_fetch_all` to disallow.

        Exceptions propagate to the caller.

        Args:
            instr: A single :class:`~id_translation.fetching.types.FetchInstruction` instance.

        Returns:
            A single :class:`~id_translation.offline.types.PlaceholderTranslations` instance.

        See Also:
            🔑 This is a key event method. See :ref:`key-events` for details.
        """

    def _fetch_translations(
        self,
        source: SourceType,
        placeholders: PlaceholdersTuple,
        *,
        required_placeholders: set[str],
        placeholder_attributes: PlaceholderAttributes | None,
        task_id: int,
        enable_uuid_heuristics: bool,
        mapper: Mapper[str, str, SourceType],
        ids: set[IdType] | None = None,
    ) -> PlaceholderTranslations[SourceType]:
        placeholders = self._deduplicate(placeholders)
        reverse_mappings, aliases, instr = self._make_fetch_instruction(
            source,
            placeholders,
            required_placeholders=required_placeholders,
            placeholder_attributes=placeholder_attributes,
            ids=ids,
            task_id=task_id,
            enable_uuid_heuristics=enable_uuid_heuristics,
            mapper=mapper,
        )

        translations = self._cache.run(
            instr,
            reverse_mappings=reverse_mappings,
            aliases=aliases,
            required_placeholders=required_placeholders,
            placeholder_attributes=placeholder_attributes,
        )

        # Fetched rows were checked before CacheAccess.store(); anything missing here came from CacheAccess.load().
        self._check_required(translations, reverse_mappings, required_placeholders, returned_by="CacheAccess.load()")
        return translations

    def _check_required(
        self,
        translations: PlaceholderTranslations[SourceType],
        reverse_mappings: dict[str, str],
        required_placeholders: set[str],
        *,
        returned_by: str,
    ) -> None:
        # An alias cannot stand in for the ID: a TranslationMap needs a real 'id' column.
        available_placeholders = {*translations.placeholders, *translations.placeholder_aliases.keys() - {ID}}
        unmapped_required_placeholders = required_placeholders.difference(available_placeholders)
        if unmapped_required_placeholders:
            self._verify_placeholders(
                reverse_mappings or {},
                translations.source,
                unmapped_required_placeholders,
                returned_by=returned_by,
            )

    @classmethod
    def _deduplicate(cls, placeholders: PlaceholdersTuple) -> PlaceholdersTuple:
        unique = []  # Hashing is slower for few elements
        for placeholder in placeholders:
            if placeholder not in unique:
                unique.append(placeholder)
        return tuple(unique)

    def _call_user_impl(self, instr: FetchInstruction[SourceType, IdType]) -> PlaceholderTranslations[SourceType]:
        start = perf_counter()

        source = instr.source
        placeholders = instr.placeholders

        logger = self.logger
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Begin fetching {'all' if instr.ids is None else len(instr.ids)} IDs from {source=}. Placeholders: {placeholders}.",
                extra=dict(
                    event_key=_logging.get_event_key(self.fetch_translations, "enter"),
                    source=source,
                    placeholders=instr.placeholders,
                    num_ids=None if instr.ids is None else len(instr.ids),
                    fetch_all=instr.fetch_all,
                    task_id=instr.task_id,
                ),
            )

        translations = self.fetch_translations(instr)

        if logger.isEnabledFor(logging.DEBUG):
            seconds = perf_counter() - start
            logger.debug(
                f"Finished fetching {len(translations.records)} IDs from source='{translations.source}'"
                f" in {fmt_sec(seconds)}. Placeholders: {translations.placeholders}.",
                extra=dict(
                    task_id=instr.task_id,
                    event_key=_logging.get_event_key(self.fetch_translations, "exit"),
                    seconds=seconds,
                    source=source,
                    placeholders=translations.placeholders,
                    num_ids=None if instr.ids is None else len(instr.ids),
                    num_ids_returned=len(translations.records),
                    fetch_all=instr.fetch_all,
                ),
            )

        return translations

    def _verify_placeholders(
        self,
        reverse_mappings: dict[str, str],
        source: SourceType,
        unmapped: set[str],
        *,
        returned_by: str | None,
    ) -> None:
        hints = []
        wanted_to_actual = reverse_dict(reverse_mappings)
        known = self.placeholders[source]
        if bad_mappings := {w: a for w, a in wanted_to_actual.items() if w in unmapped and a not in known}:
            hints.append(
                f"Mapping {bad_mappings} for required placeholders (keys) were made to placeholders that do not"
                f" exist. The override configuration {self.mapper._overrides} may be incorrect."
            )
            if bad_mappings.keys() & self.mapper._get_shared_overrides(source).keys():
                hints.append(f"Make shared overrides that {source!r} cannot satisfy source-specific.")
        if blocked := self._blocked(source, unmapped):
            hints.append(f"Overrides to '_' block the required placeholders {sorted(blocked)}.")
        actual = {wanted_to_actual.get(w, w) for w in unmapped.difference(blocked)}
        if returned_by and (advertised := sorted(actual.intersection(known))):
            hints.append(f"The source has {advertised}, but {returned_by} did not return them.")
        raise exceptions.UnknownPlaceholderError.for_placeholders(
            sorted(unmapped),
            placeholders=self.placeholders[source],
            source=source,
            caller=self,
            hints=hints,
        )

    def _make_fetch_instruction(
        self,
        source: SourceType,
        placeholders: PlaceholdersTuple,
        *,
        required_placeholders: set[str],
        placeholder_attributes: PlaceholderAttributes | None,
        ids: set[IdType] | None,
        task_id: int,
        enable_uuid_heuristics: bool,
        mapper: Mapper[str, str, SourceType],
    ) -> tuple[dict[str, str], dict[str, str], FetchInstruction[SourceType, IdType]]:
        required_placeholders.add(ID)
        if ID not in placeholders:
            placeholders = (ID, *placeholders)

        wanted_to_actual, absent = self._wanted_to_actual(source, placeholders, task_id, mapper=mapper)
        # Like id_column(), raise for an override that names a column the source does not have. Other names are
        # checked after fetching: a fetcher may return columns its source does not list, e.g. for a shared override.
        if bad := {actual: wanted for wanted, actual in absent.items() if wanted in required_placeholders}:
            self._verify_placeholders(bad, source, set(bad.values()), returned_by=None)

        placeholder_attributes = self._placeholder_attributes(wanted_to_actual, placeholder_attributes, placeholders)

        actual_to_wanted, aliases = _reverse_mappings(wanted_to_actual, placeholders)

        # Drop names the source lacks; a missing required placeholder is caught after fetching.
        def apply(c: Iterable[str]) -> Iterable[str]:
            return (wanted_to_actual[p] for p in c if p in wanted_to_actual)

        placeholders = tuple(dict.fromkeys(apply(placeholders)))  # Wanted names may share a column.
        required_placeholders = set(apply(required_placeholders))

        return (
            actual_to_wanted,
            aliases,
            FetchInstruction(
                source=source,
                placeholders=placeholders,
                required=required_placeholders,
                placeholder_attributes=placeholder_attributes,
                ids=None if ids is None else set(ids),
                task_id=task_id,
                enable_uuid_heuristics=enable_uuid_heuristics,
            ),
        )

    @classmethod
    def _placeholder_attributes(
        cls,
        wanted_to_actual: dict[str, str],
        attributes: PlaceholderAttributes | None,
        placeholders: PlaceholdersTuple,
    ) -> PlaceholderAttributes:
        if attributes is None:
            return {}

        # Remap keys in the placeholder attributes dict. The user may mix-and-match real and remapped placeholders, so
        # the target attributes have to be merged.

        rv: PlaceholderAttributes = {}
        for wanted in placeholders:
            if (actual := wanted_to_actual.get(wanted)) is None:
                continue
            merged = [*attributes.get(actual, ()), *attributes.get(wanted, ())]
            if merged:
                rv.setdefault(actual, set()).update(merged)

        return rv

    def _wanted_to_actual(
        self,
        source: SourceType,
        wanted_placeholders: Iterable[str],
        task_id: int,
        *,
        mapper: Mapper[str, str, SourceType],
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Map `wanted_placeholders`, returning the names the source has and the names mapped to columns it lacks.

        A column the source lacks can only come from an override.
        """
        mapped = self._map_placeholders(source, wanted_placeholders, candidates=None, task_id=task_id, mapper=mapper)
        available = set(self.placeholders[source])
        wanted_to_actual: dict[str, str] = {}
        absent: dict[str, str] = {}
        for wanted, actual in mapped.items():
            if actual is not None:
                (wanted_to_actual if actual in available else absent)[wanted] = actual
        return wanted_to_actual, absent

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Public in 1.x. Nothing calls them now, so an override would be ignored silently.
        if overridden := [name for name in ("default_mapper_kwargs", "default_score_function") if name in vars(cls)]:
            msg = f"{cls.__qualname__} overrides {overridden}, which are private since 2.0.0. Pass a `mapper` instead."
            raise TypeError(msg)

    # Private: the TOML factory merges [fetching.mapping] into these, so a subclass override would apply in Python only.
    # Pass a `mapper` to change them.
    @classmethod
    def _default_mapper_kwargs(cls) -> dict[str, Any]:
        """Return default :class:`~id_translation.mapping.Mapper` arguments for ``AbstractFetcher`` implementations."""
        return dict(
            score_function=HeuristicScore(
                cls._default_score_function,  # type: ignore
                heuristics=[("force_lower_case", {})],
            ),
            overrides=InheritedKeysDict(),
        )

    @classmethod
    def _default_score_function(cls, value: str, candidates: Iterable[str], context: str) -> Iterable[float]:
        """Compute score for candidates."""
        return modified_hamming(value, candidates, context)

    def __str__(self) -> str:
        return f"{type(self).__name__}(sources={format_sources(self._placeholders)})"

    def _cls_name(self) -> str:
        return tname(self, include_module=True).removeprefix(__package__ + ".")

    def __deepcopy__(self, memo: dict[int, Any] | None = None) -> Self:
        if memo is None:
            memo = {}
        cls = self.__class__
        result = cls.__new__(cls)
        memo[id(self)] = result

        for k, v in self.__dict__.items():
            setattr(result, k, deepcopy(v, memo))

        return result

    @staticmethod
    def _find_config_file(identifiers: tuple[str, ...]) -> str | None:
        for identifier in identifiers:
            if identifier.endswith(".toml"):
                return identifier
        return None

    @classmethod
    def _format_fetch_result(
        cls,
        source_translation: dict[SourceType, PlaceholderTranslations[SourceType]],
        num_ids_requested: dict[SourceType, int] | None,
    ) -> str:
        def add_requested(source: SourceType) -> str:
            if num_ids_requested is None:
                return ""

            return f"/{num_ids_requested[source]}"

        return ", ".join(
            f"[{source!r} x {pht.placeholders} x {len(pht.records)}{add_requested(source)} IDs]"
            for source, pht in source_translation.items()
        )


# TODO(python-3.13): Replace with LoggerAdapter(logger, extra, merge_extra=True).
class _ExtraLoggerAdapter(logging.LoggerAdapter[logging.Logger]):
    """Merge fixed `extra` into every record, keeping the caller's own ``extra=`` keys.

    The stdlib adapter replaces them unless ``merge_extra=True`` (3.13+).
    """

    def process(self, msg: Any, kwargs: MutableMapping[str, Any]) -> tuple[Any, MutableMapping[str, Any]]:
        kwargs["extra"] = {**(self.extra or {}), **(kwargs.get("extra") or {})}
        return msg, kwargs


def format_sources(placeholders: Mapping[Any, Any] | None) -> str:
    """Render the ``sources=`` part of a fetcher ``__str__``.

    Takes the raw `placeholders` rather than :attr:`~id_translation.types.HasSources.sources`, since resolving the
    latter triggers source discovery -- which may raise, and which ``__str__`` must not do.
    """
    if placeholders is None:
        return "<uninitialized>"
    return repr(list(placeholders)) if placeholders else "<no sources>"


def _reverse_mappings(
    wanted_to_actual: dict[str, str],
    placeholders: PlaceholdersTuple,
) -> tuple[dict[str, str], dict[str, str]]:
    """Name each fetched column by one wanted name, returning ``{actual: wanted}`` renames and aliases for the rest.

    Several wanted names may map to one column. The ID wins, then the column's own name, then placeholder order; the
    others become aliases of the chosen name instead of being lost.
    """
    by_actual: dict[str, list[str]] = {}
    for wanted in placeholders:
        if (actual := wanted_to_actual.get(wanted)) is not None:
            by_actual.setdefault(actual, []).append(wanted)

    renames: dict[str, str] = {}
    aliases: dict[str, str] = {}
    for actual, names in by_actual.items():
        chosen = ID if ID in names else actual if actual in names else names[0]
        if chosen != actual:
            renames[actual] = chosen
        aliases.update((other, chosen) for other in names if other != chosen)
    return renames, aliases
