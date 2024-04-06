import logging
import warnings
from abc import abstractmethod
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from datetime import timedelta
from pprint import pformat
from time import perf_counter
from typing import Any, Literal, final

import pandas as pd
from rics.action_level import ActionLevel
from rics.collections.dicts import InheritedKeysDict, reverse_dict
from rics.misc import tname
from rics.performance import format_seconds

from .._tasks import generate_task_id
from ..exceptions import ConnectionStatusError
from ..mapping import HeuristicScore, Mapper
from ..mapping.exceptions import MappingWarning
from ..mapping.score_functions import modified_hamming
from ..offline.types import PlaceholdersTuple, PlaceholderTranslations, SourcePlaceholderTranslations
from ..settings import logging as settings
from ..types import ID, IdType, SourceType
from . import exceptions
from ._cache import CacheAccess, CacheMetadata
from ._fetcher import Fetcher
from .types import FetchInstruction, IdsToFetch


class AbstractFetcher(Fetcher[SourceType, IdType]):
    """Base class for retrieving translations from an external source.

    .. hint::

       * Clear caches with :meth:`.CacheAccess.clear_all_cache_data`.
       * Change cache root directory with :attr:`.CacheAccess.BASE_CACHE_PATH`.

    Args:
        mapper: A :class:`.Mapper` instance used to adapt placeholder names in sources to wanted names, i.e.
            the names of the placeholders that are in the translation :class:`.Format` being used.
        allow_fetch_all: If ``False``, an error will be raised when :meth:`fetch_all` is called.
        fetch_all_unmapped_values_action: A temporary value to use for :attr:`Mapper.unmapped_values_action
            <.Mapper.unmapped_values_action>` while :meth:`fetch_all` is executing. Setting
            ``fetch_all_unmapped_values_action='raise'`` is mutually exclusive with ``selective_fetch_all=True``.
        selective_fetch_all: If ``True``, fetch only from those :attr:`~.HasSources.sources` that contain the required
            :attr:`~.HasSources.placeholders` (after mapping). May also reduce the number of placeholders retrieved.
        fetch_all_cache_max_age: If given, determines validity lifetime of data cached when :func:`fetch_all`-calls are
            made. The regular ``fetch`` function will draw from this cache as well, but only ``fetch_all`` will update
            the cache. Furthermore, caching will never be used (read or write) if :attr:`online` is ``False``.
        cache_keys: A collection of hierarchical cache-key elements, see :class:`CacheMetadata`. If given, element zero
            of the `cache_keys` is added to the :attr:`logger` name for the fetcher.
        optional: If ``True``, this fetcher may be discarded if source/placeholder-enumeration fails in multi-fetcher
            mode.

    Raises:
        rics.action_level.BadActionLevelError: If `selective_fetch_all` is ``True`` and
            `fetch_all_unmapped_values_action` is ``'raise'``.
        ValueError:  If only one of `fetch_all_cache_max_age` and `cache_keys` are given.
    """

    _FETCH: Literal["FETCH"] = "FETCH"
    _FETCH_ALL: Literal["FETCH_ALL"] = "FETCH_ALL"

    def __init__(
        self,
        mapper: Mapper[str, str, SourceType] = None,
        allow_fetch_all: bool = True,
        fetch_all_unmapped_values_action: ActionLevel.ParseType = None,
        selective_fetch_all: bool = True,
        fetch_all_cache_max_age: str | pd.Timedelta | timedelta = None,
        cache_keys: Sequence[str] | None = None,
        optional: bool = False,
    ) -> None:
        self._mapper: Mapper[str, str, SourceType] = mapper or Mapper(**self.default_mapper_kwargs())
        if self._mapper.unmapped_values_action is ActionLevel.RAISE:
            warnings.warn(
                "Using unmapped_values_action='raise' will treat optional placeholders as "
                "required placeholders during normal operation.",
                category=MappingWarning,
                stacklevel=2,
            )

        self._mapping_cache: dict[SourceType, dict[str, str | None]] = {}
        self._allow_fetch_all: bool = allow_fetch_all
        self._active_operation: Literal["FETCH", "FETCH_ALL", None] = None

        self._fetch_all_unmapped_values_action: ActionLevel | None = (
            None
            if fetch_all_unmapped_values_action is None
            else ActionLevel.verify(
                fetch_all_unmapped_values_action,
                "AbstractFetcher.fetch_all_unmapped_values_action"
                + (f" with {selective_fetch_all=}" if selective_fetch_all else ""),
                forbidden=ActionLevel.RAISE if selective_fetch_all else None,
            )
        )
        self._selective_fetch_all: bool = selective_fetch_all

        if fetch_all_cache_max_age and not cache_keys:  # pragma: no cover
            raise ValueError("Must specify at least one cache key with 'fetch_all_cache_max_age'.")
        self._translation_cache_access: CacheAccess[SourceType, IdType] | None = None
        self._fetch_all_cache_max_age: pd.Timedelta | None = (
            None if fetch_all_cache_max_age is None else pd.Timedelta(fetch_all_cache_max_age)
        )

        logger = logging.getLogger(__package__)
        mapper_logger = logging.getLogger("id_translation.mapping.placeholders")
        if cache_keys is not None:
            cache_keys = list(cache_keys)
            adder = _ExtrasAdder(config_file=cache_keys[0])
            key0 = cache_keys[0].replace(".", "-")
            logger = logger.getChild(key0)
            mapper_logger = mapper_logger.getChild(key0)
            logger.addFilter(adder)
            mapper_logger.addFilter(adder)
        self._optional: bool = optional
        self._cache_keys: list[str] | None = cache_keys
        self.logger = logger
        self._mapper.logger = mapper_logger
        self._placeholders: dict[SourceType, list[str]] | None = None

    @final
    def initialize_sources(self, task_id: int = -1, *, force: bool = False) -> None:
        if self._placeholders is None or force:
            self._placeholders = self._initialize_sources(task_id)

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

    def map_placeholders(
        self,
        source: SourceType,
        placeholders: Iterable[str],
        *,
        candidates: Iterable[str] | None = None,
        clear_cache: bool = False,
        task_id: int | None = None,
    ) -> dict[str, str | None]:
        """Map `placeholder` names to the actual names seen in `source`.

        This method calls ``Mapper.apply(values=placeholders, candidates=candidates, context=source)`` using this
        fetchers :attr:`.AbstractFetcher.mapper` instance. It is assumed that names in sources rarely change, so
        mappings are cached until the fetcher is recreated or until this method is called with ``clear_cache=True``.

        Placeholder mapping caching should not be confused with ``FETCH_ALL`` data caching.

        Args:
            source: The source to map placeholders for.
            placeholders: Desired :attr:`~.Format.placeholders`.
            candidates: A subset of candidates (placeholder names) in `source` to map with `placeholders`.
            clear_cache: If ``True``, force a full remap.
            task_id: Used for logging purposes.

        Returns:
            A dict ``{wanted_placeholder_name: actual_placeholder_name_in_source}``, where
            `actual_placeholder_name_in_source` will be ``None`` if the wanted placeholder could not be mapped to any of
            the candidates available for the source.

        Raises:
            UnknownPlaceholderError: If any of `required_placeholders` are incorrectly mapped, or not mapped at all.

        See Also:
            🔑 This is a key event method. See :ref:`key-events` for details.
        """
        start = perf_counter()

        if clear_cache or source not in self._mapping_cache:
            self._mapping_cache[source] = {}
        ans = self._mapping_cache[source]

        candidates = set(self.get_placeholders(source) if candidates is None else candidates)
        placeholders = set(placeholders).difference(ans)  # Don't remap cached mappings

        if not placeholders:
            return ans  # Nothing new to map.

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

        for actual, wanted in dm.left_to_right.items():
            ans[actual] = wanted[0]

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
        candidates: Iterable[str] | None = None,
        task_id: int | None = None,
    ) -> str | None:
        """Return the ID column for `source`."""
        return self.map_placeholders(source, [ID], candidates=candidates, task_id=task_id)[ID]

    @property
    def mapper(self) -> Mapper[str, str, SourceType]:
        """Return the ``Mapper`` instance used for placeholder name mapping."""
        return self._mapper

    @property
    def cache_enabled(self) -> bool:
        """Return the caching status for the fetcher."""
        return bool(self.online and self._fetch_all_cache_max_age)

    def clear_cache(self, reason: str) -> None:
        if not self.cache_enabled:
            raise ValueError("Not a cached instance.")  # pragma: no cover
        self._create_cache_access().clear(reason)

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

    def get_placeholders(self, source: SourceType) -> list[str]:
        """Get placeholders for `source`."""
        placeholders = self.placeholders
        if source not in placeholders:
            raise exceptions.UnknownSourceError({source}, self.sources)
        return placeholders[source]

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

    @contextmanager
    def _start_operation(self, operation):  # type: ignore  # noqa
        if self._active_operation:  # pragma: no cover
            raise exceptions.ConcurrentOperationError(operation, self._active_operation)

        self._active_operation = operation
        try:
            yield
        finally:
            self._active_operation = None

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

        with self._start_operation(self._FETCH):
            return {
                itf.source: self._fetch_translations(
                    itf.source,
                    tuple(placeholders),
                    required_placeholders=set(required),
                    ids=itf.ids,
                    task_id=task_id,
                    enable_uuid_heuristics=enable_uuid_heuristics,
                )[0]  # Second index indicates if data is from cache -- we don't care here
                for itf in ids_to_fetch
            }

    def fetch_all(
        self,
        placeholders: Iterable[str] = (),
        *,
        required: Iterable[str] = (),
        task_id: int | None = None,
        enable_uuid_heuristics: bool = False,
    ) -> SourcePlaceholderTranslations[SourceType]:
        if not self._allow_fetch_all:
            raise exceptions.ForbiddenOperationError(self._FETCH_ALL)

        if task_id is None:
            task_id = generate_task_id()

        with self._start_operation(self._FETCH_ALL), self._fetch_all_mapping_context():
            return self._fetch_all(
                tuple(placeholders),
                required_placeholders=set(required),
                task_id=task_id,
                enable_uuid_heuristics=enable_uuid_heuristics,
            )

    def _fetch_all(
        self,
        placeholders: PlaceholdersTuple,
        required_placeholders: set[str],
        task_id: int,
        enable_uuid_heuristics: bool,
    ) -> SourcePlaceholderTranslations[SourceType]:
        if self._selective_fetch_all:
            # There's nothing stopping us from doing this for regular fetching. But we assume that then the user wants
            # fetching to fail if explicit IDs can't be translated as specified.
            sources = [
                source
                for source in self.sources
                if required_placeholders.issubset(self._wanted_to_actual(source, required_placeholders, task_id))
            ]
            discarded = set(self.sources).difference(sources)
            if discarded:
                self.logger.info(
                    f"Ignoring {len(discarded)} sources {discarded} since required "
                    f"placeholders {sorted(required_placeholders)} could not be mapped by {self}.",
                    extra={"task_id": task_id},
                )
        else:
            sources = self.sources

        ans = {}
        all_from_cache = True
        for source in sources:
            translations, from_cache = self._fetch_translations(
                source,
                placeholders,
                required_placeholders=required_placeholders,
                task_id=task_id,
                enable_uuid_heuristics=enable_uuid_heuristics,
            )
            ans[source] = translations
            all_from_cache = all_from_cache and from_cache

        if all_from_cache or not self.cache_enabled:
            return ans

        event_key = f"{self.__class__.__name__.upper()}.CACHE"
        access = self._put_cached_translations(ans)
        if self.logger.isEnabledFor(logging.INFO):
            expires_at = pd.Timestamp.now() + self._fetch_all_cache_max_age
            "Wrote {count :_d} records for {len(sources)} sources to cache."
            num_records = {source: len(translations.records) for source, translations in ans.items()}

            self.logger.info(
                (
                    "Cache updated."
                    f"\n- Metadata path= '{access.metadata_path}'"
                    f"\n-    Expires at= '{expires_at.round('s')}' (in '{self._fetch_all_cache_max_age}')"
                    f"\n- Record counts= {pformat(num_records)}"
                ),
                extra=dict(
                    task_id=task_id,
                    event_key=event_key,
                    event_stage="WRITE",
                    event_title=f"{event_key}.WRITE",
                    fetch_all=True,
                    num_records=num_records,
                    cache_keys=self._cache_keys,
                    sources=sources,
                ),
            )

        return ans

    @contextmanager
    def _fetch_all_mapping_context(self):  # type: ignore  # noqa
        fetch_all_unmapped_values_action = self._fetch_all_unmapped_values_action
        selective_fetch_all = self._selective_fetch_all
        if fetch_all_unmapped_values_action is None and not selective_fetch_all:
            yield
            return

        unmapped_values_action = fetch_all_unmapped_values_action or ActionLevel.IGNORE

        if self.mapper.unmapped_values_action == unmapped_values_action:
            yield
            return

        original_mapper = self._mapper
        self._mapper = self._mapper.copy(unmapped_values_action=unmapped_values_action)
        try:
            self.logger.info(
                f"Using Mapper.{unmapped_values_action=} until the current {self._FETCH_ALL}-operation finishes, "
                f"since {selective_fetch_all=} and {fetch_all_unmapped_values_action=}."
            )
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
    ) -> tuple[PlaceholderTranslations[SourceType], bool]:
        start = perf_counter()

        placeholders = tuple(dict.fromkeys(placeholders))  # Deduplicate
        reverse_mappings, instr = self._make_fetch_instruction(
            source, placeholders, required_placeholders, ids, task_id, enable_uuid_heuristics
        )

        cached_translations = self._get_cached_translations(instr.source)
        if cached_translations is not None:
            return cached_translations, True

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
        if self.logger.isEnabledFor(log_level.enter):
            execution_time = perf_counter() - start
            self.logger.log(
                log_level.enter,
                f"Finished fetching placeholders={translations.placeholders} for {len(translations.records)} IDs "
                f"from source '{translations.source}' in {format_seconds(execution_time)}, using {self}.",
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

        if reverse_mappings:
            # The mapping is only in reverse from the Fetchers point-of-view; we're mapping back to "proper" values.
            translations.placeholders = tuple(reverse_mappings.get(p, p) for p in translations.placeholders)

        translations.id_pos = translations.placeholders.index(ID)

        unmapped_required_placeholders = required_placeholders.difference(translations.placeholders)
        if unmapped_required_placeholders:
            self._verify_placeholders(reverse_mappings or {}, source, unmapped_required_placeholders)

        return translations, False

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

    def _create_cache_access(self) -> CacheAccess[SourceType, IdType]:
        assert self._cache_keys is not None  # noqa: S101
        return CacheAccess(
            self._fetch_all_cache_max_age,
            CacheMetadata(cache_keys=self._cache_keys, placeholders=self.placeholders),
        )

    def _get_cached_translations(self, source: SourceType) -> PlaceholderTranslations[SourceType] | None:
        if not self.cache_enabled:
            return None
        if self._translation_cache_access is None:
            self._translation_cache_access = self._create_cache_access()
        return self._translation_cache_access.read_cache(source)

    def _put_cached_translations(
        self, data: SourcePlaceholderTranslations[SourceType]
    ) -> CacheAccess[SourceType, IdType]:
        self._translation_cache_access = self._create_cache_access()
        self._translation_cache_access.write_cache(data)
        return self._translation_cache_access

    @classmethod
    def default_mapper_kwargs(cls) -> dict[str, Any]:
        """Return default ``Mapper`` arguments for ``AbstractFetcher`` implementations."""
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


class _ExtrasAdder(logging.Filter):
    def __init__(self, **extras: Any) -> None:
        super().__init__()
        self.extras = extras

    def filter(self, record: logging.LogRecord) -> bool:
        for name, value in self.extras.items():
            setattr(record, name, value)
        return True
