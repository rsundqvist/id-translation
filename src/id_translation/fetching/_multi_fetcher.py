from __future__ import annotations

import logging
import warnings
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from time import perf_counter
from typing import Dict, Iterable, List, Tuple, Union

from rics.action_level import ActionLevel, ActionLevelHelper
from rics.collections.dicts import reverse_dict
from rics.misc import tname
from rics.performance import format_seconds

from ..offline.types import SourcePlaceholderTranslations
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
        optional_fetcher_discarded_log_level: If ``True``, log a warning
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
        self._source_to_fetcher_id_actual: Dict[SourceType, int] = {}
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

    @property
    def allow_fetch_all(self) -> bool:
        return all(f.allow_fetch_all for f in self._id_to_fetcher.values())  # pragma: no cover

    @property
    def online(self) -> bool:
        return all(f.online for f in self._id_to_fetcher.values())  # pragma: no cover

    @property
    def placeholders(self) -> Dict[SourceType, List[str]]:
        return {
            source: self._id_to_fetcher[self._source_to_fetcher_id[source]].placeholders[source]
            for source in self.sources
        }

    @property
    def fetchers(self) -> List[Fetcher[SourceType, IdType]]:
        """Return child fetchers."""
        return list(self._id_to_fetcher.values())

    @property
    def sources(self) -> List[SourceType]:
        return list(self._source_to_fetcher_id)

    def fetch(
        self,
        ids_to_fetch: Iterable[IdsToFetch[SourceType, IdType]],
        placeholders: Iterable[str] = (),
        required: Iterable[str] = (),
    ) -> SourcePlaceholderTranslations[SourceType]:
        tasks: Dict[int, List[IdsToFetch[SourceType, IdType]]] = {}
        sources = []
        for idt in ids_to_fetch:
            tasks.setdefault(self._source_to_fetcher_id[idt.source], []).append(idt)
            sources.append(idt.source)

        placeholders = tuple(placeholders)
        required = tuple(required)

        n_sources_and_fetchers = f"{len(sources)} sources using {len(tasks)} different fetchers"

        start = perf_counter()
        if LOGGER.isEnabledFor(logging.DEBUG):
            event_key = f"{self.__class__.__name__.upper()}.FETCH"
            LOGGER.debug(
                f"Dispatch FETCH jobs for {n_sources_and_fetchers} on {self.max_workers} threads.",
                extra=dict(
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
            return fid, fetcher.fetch(tasks[fid], placeholders, required=required)

        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix=tname(self)) as executor:
            futures = [executor.submit(fetch, fid) for fid in tasks]
            ans = self._gather(futures)

        if LOGGER.isEnabledFor(logging.DEBUG):
            execution_time = perf_counter() - start
            LOGGER.debug(
                f"Completed FETCH jobs for {n_sources_and_fetchers} in {format_seconds(execution_time)}.",
                extra=dict(
                    event_key=event_key,
                    event_stage="ENTER",
                    event_title=f"{event_key}.ENTER",
                    execution_time=execution_time,
                    sources=len(ans),
                    max_workers=self.max_workers,
                    num_fetchers=len(tasks),
                    fetch_all=False,
                ),
            )

        return ans

    def fetch_all(
        self, placeholders: Iterable[str] = (), required: Iterable[str] = ()
    ) -> SourcePlaceholderTranslations[SourceType]:
        placeholders = tuple(placeholders)
        required = tuple(required)

        start = perf_counter()
        if LOGGER.isEnabledFor(logging.DEBUG):
            event_key = f"{self.__class__.__name__.upper()}.FETCH_ALL"
            LOGGER.debug(
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
                ),
            )

        def fetch_all(fetcher: Fetcher[SourceType, IdType]) -> FetchResult[SourceType]:
            if LOGGER.isEnabledFor(logging.DEBUG):
                LOGGER.debug(f"Begin FETCH_ALL job using {self._fmt_fetcher(fetcher)}.")
            return id(fetcher), fetcher.fetch_all(placeholders, required=required)

        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix=tname(self)) as executor:
            futures = [executor.submit(fetch_all, fetcher) for fetcher in self.fetchers]
            ans = self._gather(futures)

        if LOGGER.isEnabledFor(logging.DEBUG):
            execution_time = perf_counter() - start
            LOGGER.debug(
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

    @property
    def _source_to_fetcher_id(self) -> Dict[SourceType, int]:
        if not self._source_to_fetcher_id_actual:
            source_ranks: Dict[SourceType, int] = {}
            source_to_fetcher_id: Dict[SourceType, int] = {}

            for fid, fetcher in list(self._id_to_fetcher.items()):
                if fetcher.optional:
                    try:
                        sources = fetcher.sources
                    except Exception as e:  # noqa: B902
                        sources = None
                        exception_info = f"{type(e).__name__}: {e}"
                else:
                    sources = fetcher.sources

                if not sources:
                    fetcher.close()
                    if sources is None:
                        LOGGER.log(
                            self._optional_discard_level,
                            f"Discarding optional {self._fmt_fetcher(fetcher)}: "
                            f"Raised\n    {exception_info}\nwhen getting sources.",
                        )
                    else:
                        LOGGER.warning(f"Discarding {self._fmt_fetcher(fetcher)}: No sources.")
                    del self._id_to_rank[fid]
                    del self._id_to_fetcher[fid]
                    continue

                rank = self._id_to_rank[fid]
                for source in sources:
                    if source in source_to_fetcher_id:
                        self._log_rejection(source, rank, source_ranks[source], translation=False)
                    else:
                        source_to_fetcher_id[source] = fid
                        source_ranks[source] = rank

            if not source_to_fetcher_id:
                warnings.warn("No fetchers left. See log output for more information.", UserWarning, stacklevel=2)
            self._source_to_fetcher_id_actual = source_to_fetcher_id

        return self._source_to_fetcher_id_actual

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
        accepted = self._fmt_fetcher(self._id_to_fetcher[rank_to_id[accepted_rank]])
        rejected = self._fmt_fetcher(self._id_to_fetcher[rank_to_id[rejected_rank]])

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
        return f"{tname(self)}({max_workers=}, fetchers={', '.join(map(str, self._id_to_fetcher.values()))})"

    def _fmt_fetcher(self, fetcher: Fetcher[SourceType, IdType]) -> str:
        """Format a managed fetcher with rank and hex ID."""
        fetcher_id = id(fetcher)
        rank = self._id_to_rank[fetcher_id]
        return f"rank-{rank} fetcher {fetcher} at {hex(fetcher_id)}"
