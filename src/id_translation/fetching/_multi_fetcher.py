from __future__ import annotations

import logging
import warnings
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from time import perf_counter
from typing import Dict, Iterable, List, Mapping, Optional, Tuple, Union, final

from rics.action_level import ActionLevel, ActionLevelHelper
from rics.collections.dicts import reverse_dict
from rics.misc import tname
from rics.performance import format_seconds

from .._tasks import generate_task_id
from ..offline.types import SourcePlaceholderTranslations
from ..settings import logging as settings
from ..types import IdType, SourceType
from . import Fetcher, exceptions
from .types import IdsToFetch

LOGGER = logging.getLogger(__package__).getChild("MultiFetcher")

FetchResult = Tuple[int, SourcePlaceholderTranslations[SourceType]]


_ACTION_LEVEL_HELPER = ActionLevelHelper(
    duplicate_translation_action=ActionLevel.IGNORE,
    duplicate_source_discovered_action=None,
)


class MultiFetcher(Fetcher[SourceType, IdType]):
    """Fetcher which combines the results of other fetchers.

    Args:
        *fetchers: Fetchers to wrap.
        max_workers: Number of threads to use for fetching. Fetch instructions will be dispatched using a
             :py:class:`~concurrent.futures.ThreadPoolExecutor`. Individual fetchers will be called at most once per
             ``fetch()`` or ``fetch_all()`` call made with the ``MultiFetcher``.
        duplicate_translation_action: Action to take when multiple fetchers return translations for the same source.
        duplicate_source_discovered_action: Action to take when multiple fetchers claim the same source.
        optional_fetcher_discarded_log_level: Log level used when discarding optional fetchers for any reason.
    """

    def __init__(
        self,
        *fetchers: Fetcher[SourceType, IdType],
        max_workers: int = 1,
        duplicate_translation_action: ActionLevel.ParseType = ActionLevel.WARN,
        duplicate_source_discovered_action: ActionLevel.ParseType = ActionLevel.WARN,
        optional_fetcher_discarded_log_level: Union[int, str] = "DEBUG",
    ) -> None:
        for pos, f in enumerate(fetchers):
            if not isinstance(f, Fetcher):  # pragma: no cover
                raise TypeError(f"Argument {pos} is of type {type(f)}, expected Fetcher subtype.")

        self._id_to_rank: Dict[int, int] = {id(f): rank for rank, f in enumerate(fetchers)}
        self._id_to_fetcher: Dict[int, Fetcher[SourceType, IdType]] = {id(f): f for f in fetchers}
        self.max_workers: int = max_workers
        self._duplicate_translation_action = _ACTION_LEVEL_HELPER.verify(
            duplicate_translation_action, "duplicate_translation_action"
        )
        self._duplicate_source_discovered_action = _ACTION_LEVEL_HELPER.verify(
            duplicate_source_discovered_action, "duplicate_source_discovered_action"
        )
        if isinstance(optional_fetcher_discarded_log_level, str):
            as_int = logging.getLevelName(optional_fetcher_discarded_log_level.upper())
            if not isinstance(as_int, int):
                raise ValueError(
                    f"Bad {optional_fetcher_discarded_log_level=}. Use an integer or a valid log level name."
                )
            optional_fetcher_discarded_log_level = as_int
        self._optional_discard_level = optional_fetcher_discarded_log_level

        if len(self.fetchers) != len(fetchers):
            raise ValueError("Repeat fetcher instance(s)!")  # pragma: no cover

        self._placeholders: Optional[Dict[SourceType, List[str]]] = None
        self._source_to_id: Dict[SourceType, int] = {}

    @property
    def allow_fetch_all(self) -> bool:
        return all(f.allow_fetch_all for f in self._id_to_fetcher.values())  # pragma: no cover

    @property
    def online(self) -> bool:
        return all(f.online for f in self._id_to_fetcher.values())  # pragma: no cover

    @property
    def fetchers(self) -> List[Fetcher[SourceType, IdType]]:
        """Return child fetchers."""
        return list(self._id_to_fetcher.values())

    @final
    @property
    def placeholders(self) -> Dict[SourceType, List[str]]:
        if self._placeholders is None:
            self.initialize_sources()
            return self.placeholders

        return self._placeholders

    def initialize_sources(self, task_id: int = -1, *, force: bool = False) -> None:
        if self._placeholders is None or force:
            fid_to_placeholders = self._initialize_sources(task_id)
            self._source_to_id = self._make_source_to_id(fid_to_placeholders)

            self._placeholders = {}
            for fid, placeholders in fid_to_placeholders.items():
                placeholders = {
                    source: placeholders[source] for source in placeholders if self._source_to_id[source] == fid
                }

                if placeholders:
                    self._placeholders.update(placeholders)
                else:
                    fetcher = self._id_to_fetcher[fid]
                    pretty = f"{'optional' if fetcher.optional else 'non-optional'} {self._fmt_fetcher(fetcher)}"
                    LOGGER.warning(
                        f"Discarding {pretty}: All sources found in higher-ranking fetchers.",
                        extra=dict(task_id=task_id, placeholders=placeholders),
                    )
                    fetcher.close()
                    del self._id_to_rank[fid]
                    del self._id_to_fetcher[fid]

            if not self._id_to_fetcher:
                warnings.warn("No fetchers. See log output for more information.", UserWarning, stacklevel=1)

    def _initialize_sources(self, task_id: int) -> Dict[int, Dict[SourceType, List[str]]]:
        retval: Dict[int, Dict[SourceType, List[str]]] = {}

        for fid, fetcher in list(self._id_to_fetcher.items()):
            if fetcher.optional:
                try:
                    fetcher.initialize_sources(task_id, force=True)
                    placeholders = fetcher.placeholders
                except Exception as e:  # noqa: B902
                    LOGGER.log(
                        self._optional_discard_level,
                        "Discarding optional %s: Raised\n    %s\nwhen getting sources.",
                        self._fmt_fetcher(fid),
                        f"{type(e).__name__}: {e}",
                    )
                    fetcher.close()
                    del self._id_to_rank[fid]
                    del self._id_to_fetcher[fid]
                    continue
            else:
                fetcher.initialize_sources(task_id, force=True)
                placeholders = fetcher.placeholders

                if len(placeholders) == 0:
                    level = self._optional_discard_level if fetcher.optional else logging.WARNING
                    if LOGGER.isEnabledFor(level):
                        pretty = f"{'optional' if fetcher.optional else 'non-optional'} {self._fmt_fetcher(fetcher)}"
                        LOGGER.log(level, f"Discarding {pretty}: No sources.")
                    fetcher.close()
                    del self._id_to_rank[fid]
                    del self._id_to_fetcher[fid]
                    continue

            retval[fid] = placeholders

        return retval

    def _make_source_to_id(self, fid_to_placeholders: Mapping[int, Iterable[SourceType]]) -> Dict[SourceType, int]:
        if not fid_to_placeholders:
            return {}

        source_ranks: Dict[SourceType, int] = {}
        retval: Dict[SourceType, int] = {}

        for fid, sources in fid_to_placeholders.items():
            rank = self._id_to_rank[fid]
            for source in sources:
                if source in retval:
                    self._log_rejection(source, rank, source_ranks[source], translation=False)
                else:
                    retval[source] = fid
                    source_ranks[source] = rank

        return retval

    def fetch(
        self,
        ids_to_fetch: Iterable[IdsToFetch[SourceType, IdType]],
        placeholders: Iterable[str] = (),
        *,
        required: Iterable[str] = (),
        task_id: int = None,
        enable_uuid_heuristics: bool = False,
    ) -> SourcePlaceholderTranslations[SourceType]:
        if task_id is None:
            task_id = generate_task_id()

        tasks: Dict[int, List[IdsToFetch[SourceType, IdType]]] = {}
        sources = []
        for idt in ids_to_fetch:
            tasks.setdefault(self._source_to_id[idt.source], []).append(idt)
            sources.append(idt.source)

        placeholders = tuple(placeholders)
        required = tuple(required)

        n_sources_and_fetchers = f"{len(sources)} sources using {len(tasks)} different fetchers"

        start = perf_counter()
        log_level = settings.MULTI_FETCH
        if LOGGER.isEnabledFor(log_level.enter):
            event_key = f"{self.__class__.__name__.upper()}.FETCH"
            LOGGER.log(
                log_level.enter,
                f"Dispatch FETCH jobs for {n_sources_and_fetchers} on {self.max_workers} threads.",
                extra=dict(
                    task_id=task_id,
                    event_key=event_key,
                    event_stage="ENTER",
                    event_title=f"{event_key}.ENTER",
                    sources=sources,
                    placeholders=placeholders,
                    required_placeholders=required,
                    max_workers=self.max_workers,
                    num_fetchers=len(tasks),
                    fetch_all=False,
                ),
            )

        def fetch(fid: int) -> FetchResult[SourceType]:
            fetcher = self._id_to_fetcher[fid]
            if LOGGER.isEnabledFor(logging.DEBUG):
                LOGGER.debug(f"Begin FETCH job for {len(tasks[fid])} sources using {self._fmt_fetcher(fetcher)}.")

            result = fetcher.fetch(
                tasks[fid],
                placeholders,
                required=required,
                task_id=task_id,
                enable_uuid_heuristics=enable_uuid_heuristics,
            )
            return fid, result

        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix=tname(self)) as executor:
            futures = [executor.submit(fetch, fid) for fid in tasks]
            ans = self._gather(futures)

        if LOGGER.isEnabledFor(log_level.exit):
            execution_time = perf_counter() - start
            LOGGER.log(
                log_level.exit,
                f"Completed FETCH jobs for {n_sources_and_fetchers} in {format_seconds(execution_time)}.",
                extra=dict(
                    task_id=task_id,
                    event_key=event_key,
                    event_stage="EXIT",
                    event_title=f"{event_key}.EXIT",
                    execution_time=execution_time,
                    sources=len(ans),
                    max_workers=self.max_workers,
                    num_fetchers=len(tasks),
                    fetch_all=False,
                ),
            )

        return ans

    def fetch_all(
        self,
        placeholders: Iterable[str] = (),
        *,
        required: Iterable[str] = (),
        task_id: int = None,
        enable_uuid_heuristics: bool = False,
    ) -> SourcePlaceholderTranslations[SourceType]:
        if task_id is None:
            task_id = generate_task_id()

        placeholders = tuple(placeholders)
        required = tuple(required)

        start = perf_counter()
        log_level = settings.MULTI_FETCH_ALL
        event_key = f"{self.__class__.__name__.upper()}.FETCH_ALL"
        if LOGGER.isEnabledFor(log_level.enter):
            LOGGER.log(
                log_level.enter,
                f"Dispatch FETCH_ALL jobs for {len(self.fetchers)} fetchers on {self.max_workers} threads.",
                extra=dict(
                    event_key=event_key,
                    event_stage="ENTER",
                    event_title=f"{event_key}.ENTER",
                    placeholders=placeholders,
                    required_placeholders=required,
                    max_workers=self.max_workers,
                    num_fetchers=len(self.fetchers),
                    fetch_all=True,
                    task_id=task_id,
                ),
            )

        debug_logging_enabled = LOGGER.isEnabledFor(logging.DEBUG)

        def fetch_all(fetcher: Fetcher[SourceType, IdType]) -> FetchResult[SourceType]:
            if debug_logging_enabled:
                LOGGER.debug(f"Begin FETCH_ALL job using {self._fmt_fetcher(fetcher)}.")

            result = fetcher.fetch_all(
                placeholders,
                required=required,
                task_id=task_id,
                enable_uuid_heuristics=enable_uuid_heuristics,
            )
            return id(fetcher), result

        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix=tname(self)) as executor:
            futures = [executor.submit(fetch_all, fetcher) for fetcher in self.fetchers]
            ans = self._gather(futures)

        if LOGGER.isEnabledFor(log_level.exit):
            execution_time = perf_counter() - start
            LOGGER.log(
                log_level.exit,
                f"Completed FETCH_ALL jobs for {len(ans)} sources using "
                f"{len(self.fetchers)} fetchers in {format_seconds(execution_time)}.",
                extra=dict(
                    event_key=event_key,
                    event_stage="EXIT",
                    event_title=f"{event_key}.EXIT",
                    execution_time=execution_time,
                    sources=list(ans),
                    max_workers=self.max_workers,
                    num_fetchers=len(self.fetchers),
                    fetch_all=True,
                    task_id=task_id,
                ),
            )
        return ans

    @property
    def duplicate_translation_action(self) -> ActionLevel:
        """Return action to take when multiple fetchers return translations for the same source."""
        return self._duplicate_translation_action

    @property
    def duplicate_source_discovered_action(self) -> ActionLevel:
        """Return action to take when multiple fetchers claim the same source."""
        return self._duplicate_source_discovered_action

    def _gather(self, futures: Iterable[Future[FetchResult[SourceType]]]) -> SourcePlaceholderTranslations[SourceType]:
        ans: SourcePlaceholderTranslations[SourceType] = {}
        source_ranks: Dict[SourceType, int] = {}

        for future in as_completed(futures):
            fid, translations = future.result()
            rank = self._id_to_rank[fid]
            self._process_future_result(translations, rank, source_ranks, ans)
        return ans

    def _process_future_result(
        self,
        translations: SourcePlaceholderTranslations[SourceType],
        rank: int,
        source_ranks: Dict[SourceType, int],
        ans: SourcePlaceholderTranslations[SourceType],
    ) -> None:
        for source_translations in translations.values():
            source = source_translations.source
            other_rank = source_ranks.setdefault(source, rank)

            if other_rank != rank:
                self._log_rejection(source, rank, other_rank, translation=True)
                if rank > other_rank:
                    continue  # Don't save -- other rank is greater (lower-is-better).

            ans[source] = source_translations

    def _log_rejection(self, source: SourceType, rank0: int, rank1: int, translation: bool) -> None:  # pragma: no cover
        accepted_rank, rejected_rank = (rank0, rank1) if rank0 < rank1 else (rank1, rank0)

        rank_to_id = reverse_dict(self._id_to_rank)
        accepted = self._fmt_fetcher(rank_to_id[accepted_rank])
        rejected = self._fmt_fetcher(rank_to_id[rejected_rank])

        msg = (
            f"Discarded translations for {source=} retrieved from {rejected} since the {accepted} returned "
            "translations for the same source."
            if translation
            else f"Discarded {source=} retrieved from {rejected} since the {accepted} already claimed same source."
        )

        msg += " Hint: Rank is determined input order at initialization."

        action = self.duplicate_translation_action if translation else self.duplicate_source_discovered_action

        if action is ActionLevel.IGNORE:
            LOGGER.debug(msg)
        else:
            if action is ActionLevel.RAISE:
                LOGGER.error(msg)
                raise exceptions.DuplicateSourceError(msg)
            else:
                warnings.warn(msg, exceptions.DuplicateSourceWarning, stacklevel=2)
                LOGGER.warning(msg)

    def __repr__(self) -> str:
        max_workers = self.max_workers
        fetchers = "\n    ".join(map(str, self._id_to_fetcher.values()))
        return f"{tname(self)}({max_workers=}, fetchers=[\n    {fetchers}\n])"

    def _fmt_fetcher(self, fetcher: Union[int, Fetcher[SourceType, IdType]]) -> str:
        """Format a managed fetcher with rank and hex ID."""
        if isinstance(fetcher, int):
            fetcher = self._id_to_fetcher[fetcher]
        fetcher_id = id(fetcher)
        rank = self._id_to_rank[fetcher_id]
        return f"rank-{rank} fetcher {fetcher} at {hex(fetcher_id)}"
