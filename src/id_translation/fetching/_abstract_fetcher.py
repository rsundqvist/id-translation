import logging
import warnings
from abc import abstractmethod
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from copy import deepcopy
from time import perf_counter
from typing import Any, Self, final

from rics.collections.dicts import InheritedKeysDict, reverse_dict
from rics.misc import tname
from rics.strings import format_seconds as fmt_sec

from .._tasks import generate_task_id
from ..exceptions import ConnectionStatusError
from ..mapping import HeuristicScore, Mapper
from ..mapping.exceptions import MappingWarning
from ..mapping.score_functions import modified_hamming
from ..offline.types import PlaceholdersTuple, PlaceholderTranslations, SourcePlaceholderTranslations
from ..settings import logging as settings
from ..types import ID, IdType, SourceType
from . import exceptions
from ._cache_access import CacheAccess
from ._fetcher import Fetcher
from .exceptions import CacheAccessNotAvailableError
from .types import FetchInstruction, IdsToFetch


class AbstractFetcher(Fetcher[SourceType, IdType]):
    """Base class for retrieving translations from an external source.

    Args:
        mapper: A :class:`.Mapper` instance used to adapt placeholder names in sources to wanted names, i.e.
            the names of the placeholders that are in the translation :class:`.Format` being used.
        allow_fetch_all: If ``False``, an error will be raised when :meth:`fetch_all` is called.
        selective_fetch_all: If ``True``, fetch only from those :attr:`~.HasSources.sources` that contain the required
            :attr:`~.HasSources.placeholders` (after mapping). May reduce the number of sources retrieved.
        identifiers: A collection of hierarchical identifiers. If given, element zero
            of the `identifiers` is added to the :attr:`logger` name for the fetcher.
        optional: If ``True``, this fetcher may be discarded if source/placeholder-enumeration fails in multi-fetcher
            mode.
        cache_access: A :class:`.CacheAccess` instance. Defaults to a NOOP-implementation (i.e. always fetch new data).
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
        self._mapper: Mapper[str, str, SourceType] = mapper or Mapper(**self.default_mapper_kwargs())
        if self._mapper.on_unmapped == "raise":
            warnings.warn(
                "Using on_unmapped='raise' will treat optional placeholders as "
                "required placeholders during normal operation.",
                category=MappingWarning,
                stacklevel=2,
            )

        self._allow_fetch_all: bool = allow_fetch_all
        self._selective_fetch_all = selective_fetch_all

        logger = logging.getLogger(__package__)
        mapper_logger = logging.getLogger("id_translation.mapping.placeholders")
        if identifiers is None:
            identifiers = ()
        else:
            identifiers = (*identifiers,)
            adder = _ExtrasAdder(config_file=identifiers[0])
            key0 = identifiers[0].replace(".", "-")
            logger = logger.getChild(key0)
            mapper_logger = mapper_logger.getChild(key0)
            logger.addFilter(adder)
            mapper_logger.addFilter(adder)
        self._optional = optional
        self._identifiers: tuple[str, ...] = identifiers
        self.logger = logger
        self._mapper.logger = mapper_logger
        self._placeholders: dict[SourceType, list[str]] | None = None

        if cache_access is None:
            cache_access = _NOOP_CACHE_ACCESS
        else:
            cache_access.set_parent(self)
        self._cache_access = cache_access

    @final
    def initialize_sources(self, task_id: int = -1, *, force: bool = False) -> None:
        if self._placeholders is None or force:
            self._placeholders = self._initialize_sources(task_id)
            if self._placeholders is None:
                msg = f"Call to {self._initialize_sources.__qualname__}() failed."
                raise RuntimeError(msg)

    @abstractmethod
    def _initialize_sources(self, task_id: int) -> dict[SourceType, list[str]]:
        """Perform a full (re) discovery of sources and placeholders."""

    @final
    @property
    def selective_fetch_all(self) -> bool:
        """If set, reduce the amount of data fetched by :meth:`fetch_all`."""
        return self._selective_fetch_all

    @final
    @property
    def placeholders(self) -> dict[SourceType, list[str]]:
        if self._placeholders is None:
            self.initialize_sources()
            return self.placeholders

        return self._placeholders

    @final
    @property
    def sources(self) -> list[SourceType]:
        return list(self.placeholders)

    @final
    @property
    def identifiers(self) -> tuple[str, ...]:
        """A collection of hierarchical identifiers for this fetcher."""
        return self._identifiers

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
        :attr:`.AbstractFetcher.mapper` instance.

        Args:
            source: The source to map placeholders for.
            placeholders: Desired :attr:`~.Format.placeholders`.
            candidates: A subset of candidates (placeholder names) in `source` to map with `placeholders`.
            task_id: Used for logging purposes.

        Returns:
            A dict ``{wanted_placeholder_name: actual_placeholder_name_in_source}``, where
            `actual_placeholder_name_in_source` will be ``None`` if the wanted placeholder could not be mapped to any of
            the candidates available for the source.

        Raises:
            UnknownSourceError: If `source` is not in :attr:`sources`.

        See Also:
            🔑 This is a key event method. See :ref:`key-events` for details.
        """
        start = perf_counter()

        if self._placeholders is not None and source not in self._placeholders:
            # Check the underlying attribute to avoid infinite recursion in _initialize_sources()-implementations that
            # call this method. This is typically done indirectly via id_column(), which requires explicit candidates.
            raise exceptions.UnknownSourceError({source}, self.sources)
        if candidates is None:
            # May lead to infinite recursion if _initialize_sources() calls map_placeholders(candidates=None).
            candidates = self.placeholders[source]

        candidates = set(candidates)
        placeholders = set(placeholders)

        log_level = settings.MAP_PLACEHOLDERS
        if self.logger.isEnabledFor(log_level.enter):
            event_key = f"{self.__class__.__name__.upper()}.MAP_PLACEHOLDERS"
            self.logger.log(
                log_level.enter,
                f"Begin wanted-to-actual placeholder mapping of {placeholders=} to actual placeholders={candidates}"
                f" for {source=}.",
                extra=dict(
                    task_id=task_id,
                    event_key=event_key,
                    event_stage="ENTER",
                    event_title=f"{event_key}.ENTER",
                    values=list(placeholders),
                    candidates=list(candidates),
                    context=source,
                ),
            )

        dm = self.mapper.apply(placeholders, candidates, context=source)

        ans: dict[str, str | None] = dm.flatten()  # type: ignore[assignment]
        for not_mapped in placeholders.difference(ans):
            ans[not_mapped] = None

        if self.logger.isEnabledFor(log_level.exit):
            execution_time = perf_counter() - start
            self.logger.log(
                log_level.exit,
                f"Finished wanted-to-actual placeholder mapping of {placeholders=} to actual placeholders={candidates}"
                f" for {source=}: {dm.left_to_right}.",
                extra=dict(
                    task_id=task_id,
                    event_key=event_key,
                    event_stage="EXIT",
                    event_title=f"{event_key}.EXIT",
                    execution_time=execution_time,
                    mapping=dm.left_to_right,
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
        """Return the ID column for `source`."""
        if not candidates:
            msg = f"Bad {candidates=} argument; must be a non-empty collection."
            raise TypeError(msg)
        return self.map_placeholders(source, [ID], candidates=candidates, task_id=task_id)[ID]

    @property
    def mapper(self) -> Mapper[str, str, SourceType]:
        """Return the ``Mapper`` instance used for placeholder name mapping."""
        return self._mapper

    @property
    def cache_access(self) -> CacheAccess[SourceType, IdType]:
        """Return the :class:`.CacheAccess` for this fetcher."""
        cache_access = self._cache_access

        if cache_access is not _NOOP_CACHE_ACCESS:
            return cache_access

        link = "https://id-translation.readthedocs.io/en/stable/documentation/examples/caching/caching.html"
        msg = f"{self} does not have a `CacheAccess`.\nHint: {link}"
        raise CacheAccessNotAvailableError(msg)

    @property
    def online(self) -> bool:
        return False  # pragma: no cover

    def assert_online(self) -> None:
        """Raise an error if offline.

        Raises:
            ConnectionStatusError: If not online.
        """
        if not self.online:  # pragma: no cover
            raise ConnectionStatusError("disconnected")

    @property
    def allow_fetch_all(self) -> bool:
        return self._allow_fetch_all

    @property
    def logger(self) -> logging.Logger:
        """Return the ``Logger`` that is used by this instance."""
        return self._logger

    @logger.setter
    def logger(self, logger: logging.Logger) -> None:
        self._logger = logger

    @property
    def optional(self) -> bool:
        return self._optional

    def fetch(
        self,
        ids_to_fetch: Iterable[IdsToFetch[SourceType, IdType]],
        placeholders: Iterable[str] = (),
        required: Iterable[str] = (),
        task_id: int | None = None,
        enable_uuid_heuristics: bool = False,
    ) -> SourcePlaceholderTranslations[SourceType]:
        if task_id is None:
            task_id = generate_task_id()

        return {
            itf.source: self._fetch_translations(
                itf.source,
                tuple(placeholders),
                required_placeholders=set(required),
                ids=itf.ids,
                task_id=task_id,
                enable_uuid_heuristics=enable_uuid_heuristics,
            )
            for itf in ids_to_fetch
        }

    def fetch_all(
        self,
        placeholders: Iterable[str] = (),
        *,
        required: Iterable[str] = (),
        sources: set[SourceType] | None = None,
        task_id: int | None = None,
        enable_uuid_heuristics: bool = False,
    ) -> SourcePlaceholderTranslations[SourceType]:
        if not self._allow_fetch_all:
            raise exceptions.ForbiddenOperationError("FETCH_ALL", reason=f"not allowed by {self}.")

        if task_id is None:
            task_id = generate_task_id()

        with self._fetch_all_mapping_context():
            return self._fetch_all(
                tuple(placeholders),
                required_placeholders=set(required),
                wanted_sources=sources,
                task_id=task_id,
                enable_uuid_heuristics=enable_uuid_heuristics,
            )

    def _fetch_all(
        self,
        placeholders: PlaceholdersTuple,
        required_placeholders: set[str],
        wanted_sources: set[SourceType] | None,
        task_id: int,
        enable_uuid_heuristics: bool,
    ) -> SourcePlaceholderTranslations[SourceType]:
        if wanted_sources is None:
            wanted_sources = {*self.sources}

        if self._selective_fetch_all:
            # There's nothing stopping us from doing this for regular fetching. But we assume that then the user wants
            # fetching to fail if explicit IDs can't be translated as specified.
            sources = [
                source
                for source in wanted_sources
                if required_placeholders.issubset(self._wanted_to_actual(source, required_placeholders, task_id))
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
                task_id=task_id,
                enable_uuid_heuristics=enable_uuid_heuristics,
            )
            source_translations[source] = translations

        return source_translations

    @contextmanager
    def _fetch_all_mapping_context(self):  # type: ignore  # noqa
        original_mapper = self._mapper

        on_unmapped = "ignore"
        selective_fetch_all = self._selective_fetch_all
        if not (selective_fetch_all and original_mapper.on_unmapped != on_unmapped):
            yield
            return

        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(
                f"Using Mapper.{on_unmapped=} until the current {self.fetch_all.__qualname__}-operation"
                f" finishes, since {selective_fetch_all=}."
            )
        self._mapper = self._mapper.copy(on_unmapped=on_unmapped)
        try:
            yield
        finally:
            self._mapper = original_mapper

    @abstractmethod
    def fetch_translations(self, instr: FetchInstruction[SourceType, IdType]) -> PlaceholderTranslations[SourceType]:
        """Retrieve placeholder translations from the source.

        Args:
            instr: A single :class:`.FetchInstruction` for IDs to fetch. If IDs is ``None``, the fetcher should
                retrieve data for as many IDs as possible.

        Returns:
            Placeholder translation elements.

        Raises:
            UnknownPlaceholderError: If the placeholder is unknown to the fetcher.

        See Also:
            🔑 This is a key event method. See :ref:`key-events` for details.
        """

    def _fetch_translations(
        self,
        source: SourceType,
        placeholders: PlaceholdersTuple,
        *,
        required_placeholders: set[str],
        task_id: int,
        enable_uuid_heuristics: bool,
        ids: set[IdType] | None = None,
    ) -> PlaceholderTranslations[SourceType]:
        placeholders = (*{*placeholders},)  # Deduplicate
        reverse_mappings, instr = self._make_fetch_instruction(
            source,
            placeholders,
            required_placeholders=required_placeholders,
            ids=ids,
            task_id=task_id,
            enable_uuid_heuristics=enable_uuid_heuristics,
        )

        translations: PlaceholderTranslations[SourceType] | None = None

        cache = self._cache_access
        logger: logging.Logger | None = None
        store_cache = False

        def log_cache(msg: str, event: str) -> None:
            if logger is None:
                return

            pretty = f"{type(cache).__name__}[{source=}]"
            logger.debug(msg.format(pretty), extra={"source": instr.source, "task_id": task_id, "cache_event": event})

        if cache.enabled:
            logger = self.logger
            if not logger.isEnabledFor(logging.DEBUG):
                logger = None

            translations = cache.load(instr)
            store_cache = translations is None

            if logger:
                value = f"{len(translations.records)} IDs" if translations else None
                cache_event = "hit" if translations else "miss"
                log_cache(f"{{}}.load() returned {value}.", cache_event)

        if translations is None:
            translations = self._call_user_impl(instr)

        if reverse_mappings:
            # The mapping is only in reverse from the Fetchers point-of-view; we're mapping back to "proper" values.
            translations.placeholders = tuple(reverse_mappings.get(p, p) for p in translations.placeholders)

        translations.id_pos = translations.placeholders.index(ID)

        unmapped_required_placeholders = required_placeholders.difference(translations.placeholders)
        if unmapped_required_placeholders:
            self._verify_placeholders(reverse_mappings or {}, source, unmapped_required_placeholders)

        if store_cache:
            log_cache(f"Calling {{}}.store() with {len(translations.records)} IDs.", "store")
            cache.store(instr, translations)

        return translations

    def _call_user_impl(self, instr: FetchInstruction[SourceType, IdType]) -> PlaceholderTranslations[SourceType]:
        start = perf_counter()

        source = instr.source
        placeholders = instr.placeholders

        log_level = settings.FETCH_TRANSLATIONS
        if self.logger.isEnabledFor(log_level.enter):
            event_key = f"{self.__class__.__name__.upper()}.FETCH_TRANSLATIONS"
            self.logger.log(
                log_level.enter,
                f"Begin fetching {placeholders=} from {source=} for {'all' if instr.ids is None else len(instr.ids)} IDs.",
                extra=dict(
                    event_key=event_key,
                    event_stage="ENTER",
                    event_title=f"{event_key}.ENTER",
                    source=source,
                    placeholders=instr.placeholders,
                    required_placeholders=list(instr.required),
                    num_ids=None if instr.ids is None else len(instr.ids),
                    fetch_all=instr.fetch_all,
                    task_id=instr.task_id,
                ),
            )

        translations = self.fetch_translations(instr)

        if self.logger.isEnabledFor(log_level.exit):
            execution_time = perf_counter() - start
            self.logger.log(
                log_level.exit,
                f"Finished fetching placeholders={translations.placeholders} for {len(translations.records)} IDs "
                f"from source '{translations.source}' in {fmt_sec(execution_time)}, using {self}.",
                extra=dict(
                    event_key=event_key,
                    event_stage="EXIT",
                    event_title=f"{event_key}.EXIT",
                    execution_time=execution_time,
                    source=source,
                    placeholders=translations.placeholders,
                    num_ids=len(translations.records),
                    fetch_all=instr.fetch_all,
                    task_id=instr.task_id,
                ),
            )

        return translations

    def _verify_placeholders(self, reverse_mappings: dict[str, str], source: SourceType, unmapped: set[str]) -> None:
        hint = ""
        if unmapped.intersection(reverse_mappings.values()):
            r = reverse_dict(reverse_mappings)
            bad_mappings = {b: r[b] for b in unmapped}
            hint = (
                f"\nHint: Mapping {bad_mappings} for required placeholders (keys) were made to placeholders that do not"
                f" exist. The override configuration {self.mapper._overrides} may be incorrect."
            )
        raise exceptions.UnknownPlaceholderError(
            f"Required placeholders {unmapped} not recognized. For {source=}, known placeholders are: "
            f"{sorted(self.placeholders[source])} for {self}.{hint}"
        )

    def _make_fetch_instruction(
        self,
        source: SourceType,
        placeholders: PlaceholdersTuple,
        required_placeholders: set[str],
        ids: set[IdType] | None,
        task_id: int,
        enable_uuid_heuristics: bool,
    ) -> tuple[dict[str, str] | None, FetchInstruction[SourceType, IdType]]:
        required_placeholders.add(ID)
        if ID not in placeholders:
            placeholders = (ID, *placeholders)

        wanted_to_actual = self._wanted_to_actual(source, placeholders, task_id)

        actual_to_wanted: dict[str, str] = reverse_dict(wanted_to_actual)
        need_placeholder_mapping = actual_to_wanted != wanted_to_actual
        if need_placeholder_mapping:
            # We'll just map what we can here. If anything is missing it'll be caught later.
            def apply(c: Iterable[str]) -> Iterable[str]:
                return (wanted_to_actual[p] for p in c if p in wanted_to_actual)

            placeholders = tuple(apply(placeholders))
            required_placeholders = set(apply(required_placeholders))

        return (
            actual_to_wanted if need_placeholder_mapping else None,
            FetchInstruction(
                source=source,
                placeholders=placeholders,
                required=required_placeholders,
                ids=None if ids is None else set(ids),
                task_id=task_id,
                enable_uuid_heuristics=enable_uuid_heuristics,
            ),
        )

    def _wanted_to_actual(
        self, source: SourceType, wanted_placeholders: Iterable[str], task_id: int | None = None
    ) -> dict[str, str]:
        wanted_to_actual = self.map_placeholders(source, wanted_placeholders, task_id=task_id)
        return {wanted: actual for wanted, actual in wanted_to_actual.items() if actual is not None}

    @classmethod
    def default_mapper_kwargs(cls) -> dict[str, Any]:
        """Return default :class:`.Mapper` arguments for ``AbstractFetcher`` implementations."""
        return dict(
            score_function=HeuristicScore(
                cls.default_score_function,  # type: ignore
                heuristics=[("force_lower_case", {})],
            ),
            overrides=InheritedKeysDict(),
        )

    @classmethod
    def default_score_function(cls, value: str, candidates: Iterable[str], context: str) -> Iterable[float]:
        """Compute score for candidates."""
        return modified_hamming(value, candidates, context)

    def __str__(self) -> str:
        class NoSources:
            def __repr__(self) -> str:
                return "<no sources>"

        sources = self.sources if self.sources else NoSources()
        return f"{tname(self)}({sources=})"

    def __deepcopy__(self, memo: dict[int, Any] = {}) -> Self:  # noqa: B006
        cls = self.__class__
        result = cls.__new__(cls)
        memo[id(self)] = result

        for k, v in self.__dict__.items():
            setattr(result, k, deepcopy(v, memo))

        return result


class _ExtrasAdder(logging.Filter):
    def __init__(self, **extras: Any) -> None:
        super().__init__()
        self.extras = extras

    def filter(self, record: logging.LogRecord) -> bool:
        for name, value in self.extras.items():
            setattr(record, name, value)
        return True


class NoopCacheAccess(CacheAccess[Any, Any]):
    @property
    def enabled(self) -> bool:
        return False

    def _raise(self, *_: Any, **__: Any) -> None:
        raise NotImplementedError

    store = _raise
    load = _raise


_NOOP_CACHE_ACCESS = NoopCacheAccess()
