import logging
import warnings
from collections.abc import Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from copy import deepcopy
from time import perf_counter
from typing import Any, Literal, Never, Self

from rics.collections.dicts import reverse_dict
from rics.logs import LogLevel, convert_log_level
from rics.misc import tname
from rics.strings import format_seconds as fmt_sec
from rics.types import LiteralHelper

from ..logging import generate_task_id, get_event_key
from ..offline.types import SourcePlaceholderTranslations
from ..types import IdType, SourceType
from . import AbstractFetcher, Fetcher, exceptions
from .types import IdsToFetch, Operation

LOGGER = logging.getLogger(__package__).getChild("MultiFetcher")

FetchResult = tuple[int, SourcePlaceholderTranslations[SourceType]]

OnSourceConflict = Literal["raise", "warn", "ignore"]


class MultiFetcher(Fetcher[SourceType, IdType]):
    """Fetcher which combines the results of other fetchers.

    Args:
        *children: Fetchers to wrap.
        max_workers: Number of threads to use for fetching. Fetch instructions will be dispatched using a
             :py:class:`~concurrent.futures.ThreadPoolExecutor`. Individual fetchers will be called at most once per
             ``fetch()`` or ``fetch_all()`` call made with the ``MultiFetcher``.
        on_source_conflict: Action to take when multiple fetchers :meth:`claim <.Fetcher.initialize_sources>` the same source.
        fetcher_discarded_log_level: Level used when discarding :attr:`~.Fetcher.optional` fetchers.
    """

    def __init__(
        self,
        *children: Fetcher[SourceType, IdType],
        max_workers: int = 1,
        on_source_conflict: OnSourceConflict = "raise",
        fetcher_discarded_log_level: LogLevel = "DEBUG",
    ) -> None:
        for pos, f in enumerate(children):
            if not isinstance(f, Fetcher):  # pragma: no cover
                raise TypeError(f"Argument {pos} is of type {type(f)}, expected Fetcher subtype.")

        self._id_to_rank: dict[int, int] = {id(f): rank for rank, f in enumerate(children)}
        self._id_to_fetcher: dict[int, Fetcher[SourceType, IdType]] = {id(f): f for f in children}
        self.max_workers: int = max_workers

        self._on_source_conflict = OSC_HELPER.check(on_source_conflict)
        self._discard_level = convert_log_level(fetcher_discarded_log_level, name="fetcher_discarded_log_level")

        if len(self._id_to_rank) != len(children):
            raise ValueError("Repeat fetcher instance(s)!")  # pragma: no cover

        self._placeholders: dict[SourceType, list[str]] | None = None
        self._source_to_id: dict[SourceType, int] = {}

    @property
    def allow_fetch_all(self) -> bool:
        return all(f.allow_fetch_all for f in self._id_to_fetcher.values())  # pragma: no cover

    @property
    def online(self) -> bool:
        return all(f.online for f in self._id_to_fetcher.values())  # pragma: no cover

    def close(self) -> None:
        """Close all :attr:`child <children>` fetchers."""
        for fetcher in self.children:
            fetcher.close()

    @property
    def children(self) -> list[Fetcher[SourceType, IdType]]:
        """Return child fetchers sorted by rank."""
        self.initialize_sources()
        children = [*self._id_to_fetcher.values()]
        # children.sort(key=lambda fetcher: self._id_to_rank[id(fetcher)])
        return children

    def get_child(self, source: SourceType) -> Fetcher[SourceType, IdType]:
        """Return child fetcher for the given source."""
        self.initialize_sources()

        child_id = self._source_to_id[source]
        fetcher = self._id_to_fetcher[child_id]
        return fetcher

    def get_sources(self, child: Fetcher[SourceType, IdType] | int) -> list[SourceType]:
        """Return sources for the given child."""
        if not isinstance(child, int):
            child = id(child)
        self.initialize_sources()
        return [source for source, child_id in self._source_to_id.items() if child_id == child]

    @property
    def placeholders(self) -> dict[SourceType, list[str]]:
        if self._placeholders is None:
            self.initialize_sources()
            return self.placeholders

        return self._placeholders

    def initialize_sources(self, task_id: int | None = None, *, force: bool = False) -> None:
        """Perform source discovery.

        Perform source discovery for all :attr:`children`, discarding :attr:`optional <.Fetcher.optional>` children that
        raise or do not return any sources when their respective :meth:`.Fetcher.initialize_sources` methods are
        called.

        Args:
            task_id: Used for logging.
            force: If ``True``, perform full discovery even if sources are already known.

        See Also:
            🔑 This is a key event method. See :ref:`key-events` for details.

        Notes:
            Calling this method multiple times will not recover previously discarded optional child fetchers.
        """
        if not (self._placeholders is None or force):
            return

        start = perf_counter()
        if task_id is None:
            task_id = generate_task_id()

        LOGGER.debug(
            "Begin initialization of %i children.",
            len(self._id_to_fetcher),
            extra={"task_id": task_id, "event_key": get_event_key(self.initialize_sources, "enter")},
        )

        fid_to_placeholders = self._initialize_sources(task_id)
        self._source_to_id = self._make_source_to_id(fid_to_placeholders, task_id)

        self._placeholders = {}
        for fid, source_to_placeholders in fid_to_placeholders.items():
            discarded = dict(source_to_placeholders)
            placeholders = {
                source: placeholders
                for source, placeholders in source_to_placeholders.items()
                if self._source_to_id[source] == fid
            }

            if placeholders:
                self._placeholders.update(placeholders)
                continue

            self._handle_all_sources_outranked(task_id, fetcher_id=fid, discarded=discarded)

        if not self._id_to_fetcher:
            warnings.warn("No fetchers. See log output for more information.", UserWarning, stacklevel=1)

        if LOGGER.isEnabledFor(logging.DEBUG):
            seconds = perf_counter() - start
            event_key = get_event_key(self.initialize_sources, "exit")
            LOGGER.debug(
                f"Finished initialization {len(self._id_to_fetcher)} children and "
                f"{len(self._source_to_id)} sources in {fmt_sec(seconds)}.",
                extra={"task_id": task_id, "seconds": seconds, "event_key": event_key},
            )

    def _initialize_sources(self, task_id: int) -> dict[int, dict[SourceType, list[str]]]:
        retval: dict[int, dict[SourceType, list[str]]] = {}

        log_level = self._discard_level

        for fid, fetcher in list(self._id_to_fetcher.items()):
            if fetcher.optional:
                try:
                    fetcher.initialize_sources(task_id, force=True)
                    placeholders = fetcher.placeholders
                except Exception as e:
                    LOGGER.log(
                        log_level,
                        "Discarding optional %s: Raised\n    %s\nwhen getting sources.",
                        self.format_child(fid),
                        f"{type(e).__name__}: {e}",
                        exc_info=True,
                    )
                    fetcher.close()
                    del self._id_to_rank[fid]
                    del self._id_to_fetcher[fid]
                    continue

                if len(placeholders) == 0:
                    if LOGGER.isEnabledFor(log_level):
                        LOGGER.log(
                            log_level,
                            f"Discarding optional {self.format_child(fetcher)}: No sources.",
                            extra={"task_id": task_id},
                        )

                    fetcher.close()
                    del self._id_to_rank[fid]
                    del self._id_to_fetcher[fid]
                    continue

            else:
                try:
                    fetcher.initialize_sources(task_id, force=True)
                except Exception as e:
                    self._raise_with_notes(e, fetcher)

                placeholders = fetcher.placeholders

                if len(placeholders) == 0 and LOGGER.isEnabledFor(logging.WARNING):
                    LOGGER.warning(
                        f"Required {self.format_child(fetcher)} does not provide any sources.",
                        extra={"task_id": task_id},
                    )

            retval[fid] = placeholders

        return retval

    def _make_source_to_id(
        self,
        fid_to_placeholders: Mapping[int, Iterable[SourceType]],
        task_id: int,
    ) -> dict[SourceType, int]:
        if not fid_to_placeholders:
            return {}

        source_ranks: dict[SourceType, int] = {}
        retval: dict[SourceType, int] = {}

        for fid, sources in fid_to_placeholders.items():
            rank = self._id_to_rank[fid]
            for source in sources:
                if source in retval:
                    self._log_rejection(source, rank, source_ranks[source], "INITIALIZE_SOURCES", task_id)
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
        task_id: int | None = None,
        enable_uuid_heuristics: bool = False,
    ) -> SourcePlaceholderTranslations[SourceType]:
        if task_id is None:
            task_id = generate_task_id()
        self.initialize_sources(task_id)

        tasks: dict[int, list[IdsToFetch[SourceType, IdType]]] = {}
        sources = []
        unknown_sources = []
        for idt in ids_to_fetch:
            source = idt.source
            child_id = self._source_to_id.get(source)
            if child_id is None:
                unknown_sources.append(source)
                continue
            tasks.setdefault(child_id, []).append(idt)
            sources.append(source)

        if unknown_sources:
            raise exceptions.UnknownSourceError(unknown_sources, self.sources)

        placeholders = tuple(placeholders)
        required = tuple(required)

        n_sources_and_fetchers = f"{len(sources)} sources using {len(tasks)} different fetchers"

        start = perf_counter()
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug(
                f"Dispatch FETCH jobs for {n_sources_and_fetchers} on {self.max_workers} threads.",
                extra=dict(
                    task_id=task_id,
                    event_key=get_event_key(self.fetch, "enter"),
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
                LOGGER.debug(
                    f"Begin FETCH job for {len(tasks[fid])} sources using {self.format_child(fetcher)}.",
                    extra={"task_id": task_id},
                )

            try:
                result = fetcher.fetch(
                    tasks[fid],
                    placeholders,
                    required=required,
                    task_id=task_id,
                    enable_uuid_heuristics=enable_uuid_heuristics,
                )
            except Exception as e:
                self._raise_with_notes(e, fetcher)
            return fid, result

        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix=tname(self)) as executor:
            futures = [executor.submit(fetch, fid) for fid in tasks]
            ans = self._gather(futures, operation="FETCH", task_id=task_id)

        if LOGGER.isEnabledFor(logging.DEBUG):
            seconds = perf_counter() - start
            LOGGER.debug(
                f"Completed FETCH jobs for {n_sources_and_fetchers} in {fmt_sec(seconds)}.",
                extra=dict(
                    task_id=task_id,
                    event_key=get_event_key(self.fetch, "exit"),
                    seconds=seconds,
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
        sources: set[SourceType] | None = None,
        task_id: int | None = None,
        enable_uuid_heuristics: bool = False,
    ) -> SourcePlaceholderTranslations[SourceType]:
        if task_id is None:
            task_id = generate_task_id()
        self.initialize_sources(task_id)

        placeholders = tuple(placeholders)
        required = tuple(required)

        start = perf_counter()
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug(
                f"Dispatch FETCH_ALL jobs for {len(self.children)} fetchers on {self.max_workers} threads.",
                extra=dict(
                    task_id=task_id,
                    event_key=get_event_key(self.fetch_all, "enter"),
                    placeholders=placeholders,
                    required_placeholders=required,
                    sources=None if sources is None else [*sources],
                    max_workers=self.max_workers,
                    num_fetchers=len(self.children),
                    fetch_all=True,
                ),
            )

        def fetch_all(fetcher: Fetcher[SourceType, IdType]) -> FetchResult[SourceType]:
            result = fetcher.fetch_all(
                placeholders,
                required=required,
                sources=None if sources is None else sources.intersection(fetcher.sources),
                task_id=task_id,
                enable_uuid_heuristics=enable_uuid_heuristics,
            )
            return id(fetcher), result

        children = self.children if sources is None else [c for c in self.children if sources.intersection(c.sources)]
        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix=tname(self)) as executor:
            futures = [executor.submit(fetch_all, fetcher) for fetcher in children]
            ans = self._gather(futures, operation="FETCH_ALL", task_id=task_id)

        if LOGGER.isEnabledFor(logging.DEBUG):
            seconds = perf_counter() - start
            LOGGER.debug(
                f"Completed FETCH_ALL jobs for {len(ans)} sources using "
                f"{len(self.children)} fetchers in {fmt_sec(seconds)}.",
                extra=dict(
                    task_id=task_id,
                    event_key=get_event_key(self.fetch_all, "exit"),
                    seconds=seconds,
                    sources=list(ans),
                    max_workers=self.max_workers,
                    num_fetchers=len(self.children),
                    fetch_all=True,
                ),
            )
        return ans

    @property
    def on_source_conflict(self) -> OnSourceConflict:
        """Action to take when multiple fetchers :meth:`claim <.Fetcher.initialize_sources>` the same source."""
        return self._on_source_conflict

    def _gather(
        self,
        futures: Iterable[Future[FetchResult[SourceType]]],
        operation: Operation,
        task_id: int,
    ) -> SourcePlaceholderTranslations[SourceType]:
        ans: SourcePlaceholderTranslations[SourceType] = {}
        source_ranks: dict[SourceType, int] = {}

        for future in as_completed(futures):
            fid, translations = future.result()
            rank = self._id_to_rank[fid]
            self._process_future_result(translations, rank, source_ranks, ans, operation, task_id)
        return ans

    def _process_future_result(
        self,
        translations: SourcePlaceholderTranslations[SourceType],
        rank: int,
        source_ranks: dict[SourceType, int],
        ans: SourcePlaceholderTranslations[SourceType],
        operation: Operation,
        task_id: int,
    ) -> None:
        for source_translations in translations.values():
            source = source_translations.source
            other_rank = source_ranks.setdefault(source, rank)

            if other_rank != rank:
                self._log_rejection(source, rank, other_rank, operation, task_id)
                if rank > other_rank:
                    continue  # Don't save -- other rank is greater (lower-is-better).

            ans[source] = source_translations

    def _log_rejection(self, source: SourceType, rank0: int, rank1: int, operation: Operation, task_id: int) -> None:
        accepted_rank, rejected_rank = (rank0, rank1) if rank0 < rank1 else (rank1, rank0)

        rank_to_id = reverse_dict(self._id_to_rank)
        accepted = self.format_child(rank_to_id[accepted_rank])
        rejected = self.format_child(rank_to_id[rejected_rank])

        hints = []
        if operation == "INITIALIZE_SOURCES":
            msg = f"Discarded {source=} retrieved from {rejected} since the {accepted} already claimed same source."
            hints.append("Hint: Rank is determined input order at initialization.")
            on_source_conflict = self.on_source_conflict
        elif operation == "FETCH_ALL":
            msg = (
                f"Dropping translations for {source=} returned by the {rejected} since {operation=}."
                f" Will use {accepted} translations instead."
            )
            on_source_conflict = "ignore"
        else:  # Bad Fetcher.fetch implementation; should be rare.
            fetcher = self._id_to_fetcher[rank_to_id[rejected_rank]]
            cls = tname(fetcher, include_module=True)
            msg = f"Dropping translations for {source=} returned by the {rejected}; this source belongs to the {accepted}."
            hints.append(f"Hint: The implementation of {cls} may be incorrect.")
            on_source_conflict = "warn"

        extra = {"task_id": task_id, "source": source}
        if on_source_conflict == "raise":
            LOGGER.error(msg, extra=extra)
            exc = exceptions.DuplicateSourceError(msg)
            for hint in hints:
                exc.add_note(hint)
            raise exc
        if on_source_conflict == "warn":
            LOGGER.warning(msg, extra=extra)

            warnings.warn(msg, exceptions.DuplicateSourceWarning, stacklevel=3)
            msg += "\n".join(hints)
        elif on_source_conflict == "ignore" and LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug(msg, extra=extra)

    def __repr__(self) -> str:
        max_workers = self.max_workers
        fetchers = "\n    ".join(f"{f}," for f in self._id_to_fetcher.values())
        return f"{tname(self)}({max_workers=}, fetchers=[\n    {fetchers}\n])"

    def format_child(self, fetcher: int | Fetcher[SourceType, IdType]) -> str:
        """Format a managed fetcher with rank and hex ID."""
        if isinstance(fetcher, int):
            fetcher = self._id_to_fetcher[fetcher]
        fetcher_id = id(fetcher)
        rank = self._id_to_rank[fetcher_id]
        return f"rank-{rank} fetcher {fetcher} at {hex(fetcher_id)}"

    def _handle_all_sources_outranked(
        self, task_id: int, *, fetcher_id: int, discarded: dict[SourceType, list[str]]
    ) -> None:
        fetcher = self._id_to_fetcher[fetcher_id]

        if LOGGER.isEnabledFor(logging.WARNING) and fetcher.sources:
            reason = "All sources found in higher-ranking fetchers"
            pretty = self.format_child(fetcher)
            LOGGER.warning(
                f"Discarding optional {pretty}: {reason}."
                if fetcher.optional
                else f"Required {pretty} is useless, but will be kept: {reason}.",
                extra={"task_id": task_id, "discarded": discarded, "fetcher_id": fetcher_id},
            )

        if fetcher.optional:
            fetcher.close()
            del self._id_to_rank[fetcher_id]
            del self._id_to_fetcher[fetcher_id]

    def _raise_with_notes(self, e: BaseException, fetcher: Fetcher[SourceType, IdType]) -> Never:
        note = f"Context (added by {type(self).__name__}):"

        # Add config file. Mirrors logic used in the abstract fetcher.
        if isinstance(fetcher, AbstractFetcher):
            for idx in fetcher.identifiers:
                if idx.endswith("toml"):
                    note += f"\n -  file= '{idx}'"
                    break

        note += f"\n - child= {self.format_child(fetcher)}"
        e.add_note(note)
        raise e

    def __deepcopy__(self, memo: dict[int, Any] = {}) -> Self:  # noqa: B006
        cls = self.__class__
        result = cls.__new__(cls)
        memo[id(self)] = result

        dicts = self._copy_dicts(memo)
        for k, v in self.__dict__.items():
            setattr(result, k, dicts[k] if k in dicts else deepcopy(v, memo))

        return result

    def _copy_dicts(self, memo: dict[int, Any]) -> dict[str, dict[str, Any] | dict[int, Any]]:
        new_id_to_fetcher: dict[int, Fetcher[SourceType, IdType]] = {}
        old_id_to_new_id: dict[int, int] = {}

        members = self.__dict__

        for old_id, old_fetcher in members["_id_to_fetcher"].items():
            try:
                new_fetcher = deepcopy(old_fetcher, memo)
            except TypeError as e:
                new_fetcher = old_fetcher

                # This hides the Translator.copy(fetcher=Translator.fetcher) warning emitted in the caller!
                fetcher_cls = type(old_fetcher).__name__
                msg = f"deepcopy() failed ({type(e).__name__}: {e}). Reusing {self.format_child(old_fetcher)}"
                LOGGER.warning(msg, exc_info=True, extra={"fetcher_class": fetcher_cls})

            new_id = id(new_fetcher)
            new_id_to_fetcher[new_id] = new_fetcher
            old_id_to_new_id[old_id] = new_id

        return {
            "_id_to_fetcher": new_id_to_fetcher,
            "_id_to_rank": {old_id_to_new_id[old_id]: rank for old_id, rank in members["_id_to_rank"].items()},
            "_source_to_id": {source: old_id_to_new_id[old_id] for source, old_id in members["_source_to_id"].items()},
        }


OSC_HELPER: LiteralHelper[OnSourceConflict] = LiteralHelper(
    OnSourceConflict,
    default_name="on_source_conflict",
    type_name="OnSourceConflict",
)
