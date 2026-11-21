import logging
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from copy import deepcopy
from time import perf_counter
from types import MappingProxyType
from typing import Any, Literal, Never, Self

from rics.logs import LogLevel, convert_log_level
from rics.misc import tname
from rics.strings import format_seconds as fmt_sec
from rics.types import LiteralHelper

from .._utils.emit_warning import emit_warning
from .._utils.locks import DiscoveryGuard
from ..exceptions import MissingPlaceholderError
from ..logging import generate_task_id, get_event_key
from ..mapping.exceptions import MappingError
from ..offline.types import PlaceholderAttributes, SourcePlaceholderTranslations
from ..transform.types import Transformer
from ..types import IdType, SourceType
from . import AbstractFetcher, Fetcher, exceptions
from ._abstract_fetcher import _ExtraLoggerAdapter
from .types import FetchOperation, IdsToFetch

FetchResult = tuple[int, SourcePlaceholderTranslations[SourceType]]

OnSourceConflict = Literal["raise", "warn", "ignore"]


class MultiFetcher(Fetcher[SourceType, IdType]):
    """Fetcher which combines the results of other fetchers.

    Args:
        *children: Fetchers to wrap.
        max_workers: Number of threads to use for fetching. Fetch instructions will be dispatched using a
             :py:class:`~concurrent.futures.ThreadPoolExecutor`. Individual fetchers will be called at most once per
             ``fetch()`` or ``fetch_all()`` call made with the ``MultiFetcher``.
        on_source_conflict: Action to take when multiple fetchers
            :meth:`claim <id_translation.fetching.Fetcher.initialize_sources>` the same source.
        fetcher_discarded_log_level: Level used when discarding :attr:`~id_translation.fetching.Fetcher.optional`
            fetchers.
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
        ThreadPoolExecutor(max_workers=max_workers).shutdown()  # Validate now, not at the first fetch.
        self.max_workers: int = max_workers

        self._on_source_conflict = OSC_HELPER.check(on_source_conflict)
        self._discard_level = convert_log_level(fetcher_discarded_log_level, name="fetcher_discarded_log_level")
        self._logger = _ExtraLoggerAdapter(
            logging.getLogger(__package__).getChild(type(self).__name__),
            {
                "fetcher_class": tname(type(self), include_module=True).removeprefix(__package__ + "."),
                "fetcher_config_file": None,  # Like AbstractFetcher records; a MultiFetcher has no file of its own.
            },
        )

        if len(self._id_to_rank) != len(children):
            raise ValueError("Repeat fetcher instance(s)!")  # pragma: no cover

        self._placeholders: dict[SourceType, list[str]] | None = None
        self._source_to_id: dict[SourceType, int] = {}
        self._unresolved: list[str] = []
        self._discovery_guard = DiscoveryGuard()

    @property
    def allow_fetch_all(self) -> bool:
        return all(f.allow_fetch_all for f in [*self._id_to_fetcher.values()])  # pragma: no cover

    def close(self) -> None:
        """Close all :attr:`child <id_translation.fetching.MultiFetcher.children>` fetchers.

        Every child is closed, even if one raises; the first error is raised afterwards.
        """
        error: Exception | None = None
        for fid, fetcher in [*self._id_to_fetcher.items()]:  # Not self.children, which would run discovery first.
            try:
                fetcher.close()
            except Exception as e:
                if error is None:
                    error = e
                    e.add_note(self._context_note(fetcher))
                else:
                    self._logger.exception(f"Failed to close {self._format_child(fid)}.")
        if error is not None:
            raise error

    @property
    def children(self) -> list[Fetcher[SourceType, IdType]]:
        """Return child fetchers sorted by rank."""
        self.initialize_sources()
        return [*self._id_to_fetcher.values()]  # Insertion order is rank order.

    def _unresolved_children(self) -> list[str]:
        # Diagnostic prose for the Translator's unknown-source warning and its NoSourcesError hint: one formatted
        # entry per discarded `optional` child, in discard order. These raised from `initialize_sources`, unlike a
        # child discarded for reporting *no* sources, which is known to serve none. Children of nested MultiFetchers
        # are included.
        self.initialize_sources()
        unresolved = [*self._unresolved]
        for child in self._id_to_fetcher.values():
            if isinstance(child, MultiFetcher):
                unresolved += child._unresolved_children()
        return unresolved

    def get_child(self, source: SourceType) -> Fetcher[SourceType, IdType]:
        """Return child fetcher for the given source.

        Raises:
            UnknownSourceError: If no child serves `source`.
        """
        self.initialize_sources()

        if (child_id := self._source_to_id.get(source)) is None:
            raise exceptions.UnknownSourceError.for_sources([source], sources=self.sources)
        return self._id_to_fetcher[child_id]

    def get_sources(self, child: Fetcher[SourceType, IdType]) -> list[SourceType]:
        """Return sources for the given child.

        Raises:
            ValueError: If `child` is not a child of this ``MultiFetcher``.
        """
        self.initialize_sources()
        fid = self._child_id(child)
        return [source for source, child_id in self._source_to_id.items() if child_id == fid]

    def _child_id(self, child: Fetcher[SourceType, IdType]) -> int:
        # Children are keyed by `id()`, which copies and pickling rebuild, so an int is never accepted from callers.
        if (fid := id(child)) not in self._id_to_fetcher:
            raise ValueError(f"Not a child of this {type(self).__name__}: {child!r}.")
        return fid

    def get_transformer(self, source: SourceType) -> Transformer[IdType] | Sequence[Transformer[IdType]] | None:
        """Delegate to the child that serves `source` after source conflict resolution.

        Returns ``None`` for sources that no child serves, as the base implementation does.
        """
        self.initialize_sources()

        if source not in self._source_to_id:
            return None
        return self.get_child(source).get_transformer(source)

    def _configured_transformers(self, source: SourceType) -> Sequence[Transformer[IdType]]:
        # Only the winning child's: transformers that a discarded or outranked child brings along go with it.
        self.initialize_sources()
        if source not in self._source_to_id:
            return ()
        return self.get_child(source)._configured_transformers(source)

    @property
    def placeholders(self) -> Mapping[SourceType, Sequence[str]]:
        if self._placeholders is None:
            self.initialize_sources()
            return self.placeholders

        return MappingProxyType(self._placeholders)

    def initialize_sources(self, task_id: int | None = None) -> None:
        """Perform source discovery.

        Perform source discovery for all :attr:`~id_translation.fetching.MultiFetcher.children`, discarding
        :attr:`optional <id_translation.fetching.Fetcher.optional>` children that raise or do not return any sources
        when their respective :meth:`Fetcher.initialize_sources <id_translation.fetching.Fetcher.initialize_sources>`
        methods are called. Configuration errors and broken implementations (a
        :class:`~id_translation.mapping.exceptions.MappingError`,
        :class:`~id_translation.fetching.exceptions.DuplicateSourceError` or
        :class:`~id_translation.fetching.exceptions.ImplementationError`, a source missing a required placeholder, or an
        override naming a column the source lacks) are raised, also for optional children.

        Args:
            task_id: Used for logging.

        See Also:
            🔑 This is a key event method. See :ref:`key-events` for details.

        Notes:
            An optional child whose every source a higher-ranked child serves is discarded too.
            Calling this method multiple times will not recover previously discarded optional child fetchers.
        """
        # Mirrors AbstractFetcher.initialize_sources(); if the duplicated locking logic grows, break it out into one place.
        if self._placeholders is not None:
            return
        if self._discovery_guard.is_current():
            raise exceptions.ImplementationError(
                f"{type(self).__name__}.initialize_sources() was called during its own discovery.",
                hints="Code run during discovery, such as a child or a log handler, must not read its sources or"
                " placeholders.",
            )

        with self._discovery_guard.lock:
            if self._placeholders is not None:
                return  # Another thread finished discovery while this one waited; see AbstractFetcher for failures.

            start = perf_counter()
            if task_id is None:
                task_id = generate_task_id()

            self._discover_locked(task_id)

        if self._logger.isEnabledFor(logging.DEBUG):  # Outside the lock, as in AbstractFetcher.
            seconds = perf_counter() - start
            event_key = get_event_key(self.initialize_sources, "exit")
            self._logger.debug(
                f"Finished initialization {len(self._id_to_fetcher)} children and "
                f"{len(self._source_to_id)} sources in {fmt_sec(seconds)}.",
                extra={"task_id": task_id, "seconds": seconds, "event_key": event_key},
            )

    def _discover_locked(self, task_id: int) -> None:
        try:
            self._discovery_guard.set_current()
            self._logger.debug(
                "Begin initialization of %i children.",
                len(self._id_to_fetcher),
                extra={"task_id": task_id, "event_key": get_event_key(self.initialize_sources, "enter")},
            )

            fid_to_placeholders = self._initialize_sources(task_id)
            self._source_to_id = self._make_source_to_id(fid_to_placeholders, task_id)

            # Committed last: `_placeholders` marks discovery as done, so a raise below must leave it unset for the retry.
            all_placeholders: dict[SourceType, list[str]] = {}
            for fid, source_to_placeholders in fid_to_placeholders.items():
                discarded = dict(source_to_placeholders)
                placeholders = {
                    source: placeholders
                    for source, placeholders in source_to_placeholders.items()
                    if self._source_to_id[source] == fid
                }

                if placeholders:
                    all_placeholders.update(placeholders)
                    continue

                fetcher = self._id_to_fetcher[fid]
                _log_outranked(
                    self._logger,
                    self._format_child(fid),
                    optional=fetcher.optional,
                    discard_level=self._discard_level,
                    task_id=task_id,
                    discarded=discarded,
                )
                if fetcher.optional:
                    self._discard(fid)

            if not self._id_to_fetcher:
                emit_warning("No fetchers. See log output for more information.", exceptions.FetcherWarning)

            self._placeholders = all_placeholders
        finally:
            self._discovery_guard.clear()

    def _initialize_sources(self, task_id: int) -> dict[int, dict[SourceType, list[str]]]:
        retval: dict[int, dict[SourceType, list[str]]] = {}

        log_level = self._discard_level
        # Raised even by an `optional` child: they mean a misconfiguration or a broken implementation.
        not_suppressed = (
            MissingPlaceholderError,
            MappingError,
            exceptions.ImplementationError,
            exceptions.DuplicateSourceError,
        )

        for fid, fetcher in list(self._id_to_fetcher.items()):
            if fetcher.optional:
                try:
                    fetcher.initialize_sources(task_id)
                    placeholders = fetcher.placeholders
                except not_suppressed as e:
                    self._raise_with_notes(e, fetcher)
                except Exception as e:
                    pretty = self._format_child(fid)
                    reason = f"Raised\n    {type(e).__name__}: {e}\nwhen getting sources."
                    _log_discard(self._logger, log_level, pretty, reason, task_id=task_id, exc_info=True)
                    self._unresolved.append(pretty)
                    self._discard(fid)
                    continue

                if len(placeholders) == 0:
                    _log_discard(self._logger, log_level, self._format_child(fid), "No sources.", task_id=task_id)
                    self._discard(fid)
                    continue

            else:
                try:
                    fetcher.initialize_sources(task_id)
                except Exception as e:
                    self._raise_with_notes(e, fetcher)

                placeholders = fetcher.placeholders

                if len(placeholders) == 0 and self._logger.isEnabledFor(logging.WARNING):
                    self._logger.warning(
                        f"Required {self._format_child(fid)} does not provide any sources.",
                        extra={"task_id": task_id},
                    )

            retval[fid] = {source: list(names) for source, names in placeholders.items()}

        return retval

    def _make_source_to_id(
        self,
        fid_to_placeholders: Mapping[int, Iterable[SourceType]],
        task_id: int,
    ) -> dict[SourceType, int]:
        """The winner per source: children are visited in rank order, so the first claim wins."""
        retval: dict[SourceType, int] = {}

        for fid, sources in fid_to_placeholders.items():
            for source in sources:
                if source in retval:
                    accepted, rejected = self._format_child(retval[source]), self._format_child(fid)
                    _handle_conflict(
                        self._logger, source, accepted, rejected, self._on_source_conflict, task_id=task_id
                    )
                else:
                    retval[source] = fid

        return retval

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
            raise exceptions.UnknownSourceError.for_sources(unknown_sources, sources=self.sources)

        placeholders = tuple(placeholders)
        required = tuple(required)

        n_sources_and_fetchers = f"{len(sources)} sources using {len(tasks)} different fetchers"

        start = perf_counter()
        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug(
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
            if self._logger.isEnabledFor(logging.DEBUG):
                self._logger.debug(
                    f"Begin FETCH job for {len(tasks[fid])} sources using {self._format_child(fid)}.",
                    extra={"task_id": task_id},
                )

            try:
                result = fetcher.fetch(
                    tasks[fid],
                    placeholders,
                    required=required,
                    placeholder_attributes=placeholder_attributes,
                    task_id=task_id,
                    enable_uuid_heuristics=enable_uuid_heuristics,
                )
            except Exception as e:
                self._raise_with_notes(e, fetcher)
            return fid, result

        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix=tname(self)) as executor:
            futures = [executor.submit(fetch, fid) for fid in tasks]
            ans = self._gather(futures, operation="FETCH", task_id=task_id)

        if self._logger.isEnabledFor(logging.DEBUG):
            seconds = perf_counter() - start
            self._logger.debug(
                f"Finished FETCH jobs for {n_sources_and_fetchers} in {fmt_sec(seconds)}.",
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
        placeholder_attributes: PlaceholderAttributes | None = None,
        sources: set[SourceType] | None = None,
        task_id: int | None = None,
        enable_uuid_heuristics: bool = False,
    ) -> SourcePlaceholderTranslations[SourceType]:
        if task_id is None:
            task_id = generate_task_id()
        self.initialize_sources(task_id)
        if sources is not None and (
            unknown := [source for source in dict.fromkeys(sources) if source not in self._source_to_id]
        ):
            raise exceptions.UnknownSourceError.for_sources(unknown, sources=self.sources)

        placeholders = tuple(placeholders)
        required = tuple(required)

        tasks: dict[int, set[SourceType]] = {}
        for source, child_id in self._source_to_id.items():
            if sources is None or source in sources:
                tasks.setdefault(child_id, set()).add(source)

        start = perf_counter()
        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug(
                f"Dispatch FETCH_ALL jobs for {len(tasks)} fetchers on {self.max_workers} threads.",
                extra=dict(
                    task_id=task_id,
                    event_key=get_event_key(self.fetch_all, "enter"),
                    placeholders=placeholders,
                    required_placeholders=required,
                    placeholder_attributes={p: sorted(attrs) for p, attrs in placeholder_attributes.items()}
                    if placeholder_attributes
                    else None,
                    sources=None if sources is None else [*sources],
                    max_workers=self.max_workers,
                    num_fetchers=len(tasks),
                    fetch_all=True,
                ),
            )

        def fetch_all(fid: int) -> FetchResult[SourceType]:
            fetcher = self._id_to_fetcher[fid]
            try:
                result = fetcher.fetch_all(
                    placeholders,
                    required=required,
                    placeholder_attributes=placeholder_attributes,
                    sources=tasks[fid],
                    task_id=task_id,
                    enable_uuid_heuristics=enable_uuid_heuristics,
                )
            except Exception as e:
                self._raise_with_notes(e, fetcher)
            return fid, result

        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix=tname(self)) as executor:
            futures = [executor.submit(fetch_all, fid) for fid in tasks]
            ans = self._gather(futures, operation="FETCH_ALL", task_id=task_id)

        if self._logger.isEnabledFor(logging.DEBUG):
            seconds = perf_counter() - start
            self._logger.debug(
                f"Finished FETCH_ALL jobs for {len(ans)} sources using {len(tasks)} fetchers in {fmt_sec(seconds)}.",
                extra=dict(
                    task_id=task_id,
                    event_key=get_event_key(self.fetch_all, "exit"),
                    seconds=seconds,
                    sources=list(ans),
                    max_workers=self.max_workers,
                    num_fetchers=len(tasks),
                    fetch_all=True,
                ),
            )
        return ans

    @property
    def on_source_conflict(self) -> OnSourceConflict:
        """Action to take when multiple fetchers :meth:`claim <id_translation.fetching.Fetcher.initialize_sources>` the same source."""
        return self._on_source_conflict

    def _gather(
        self,
        futures: list[Future[FetchResult[SourceType]]],
        operation: FetchOperation,
        task_id: int,
    ) -> SourcePlaceholderTranslations[SourceType]:
        ans: SourcePlaceholderTranslations[SourceType] = {}

        try:
            for future in as_completed(futures):
                fid, translations = future.result()
                self._process_future_result(translations, fid, ans, operation=operation, task_id=task_id)
        except BaseException:
            for future in futures:
                future.cancel()
            raise
        return {source: ans[source] for source in self.sources if source in ans}  # Not in completion order.

    def _process_future_result(
        self,
        translations: SourcePlaceholderTranslations[SourceType],
        fid: int,
        ans: SourcePlaceholderTranslations[SourceType],
        *,
        operation: FetchOperation,
        task_id: int,
    ) -> None:
        for source_translations in translations.values():
            source = source_translations.source
            owner_id = self._source_to_id.get(source)
            if owner_id == fid:
                ans[source] = source_translations
                continue

            _warn_dropped_translations(
                self._logger,
                source,
                returned_by=self._format_child(fid),
                owner=None if owner_id is None else self._format_child(owner_id),
                implementation=tname(type(self._id_to_fetcher[fid]), include_module=True),
                operation=operation,
                task_id=task_id,
            )

    def __repr__(self) -> str:
        max_workers = self.max_workers
        # A snapshot: discovery in another thread may discard children while this runs.
        fetchers = "\n    ".join(f"{self._child_str(f)}," for f in [*self._id_to_fetcher.values()])
        return f"{tname(self)}({max_workers=}, fetchers=[\n    {fetchers}\n])"

    def format_child(self, fetcher: Fetcher[SourceType, IdType]) -> str:
        """Format a managed fetcher with rank, hex ID and, if known, its configuration file.

        Raises:
            ValueError: If `fetcher` is not a child of this ``MultiFetcher``.
        """
        return self._format_child(self._child_id(fetcher))

    def _format_child(self, fetcher_id: int) -> str:
        fetcher = self._id_to_fetcher[fetcher_id]
        pretty = f"rank-{self._id_to_rank[fetcher_id]} fetcher {self._child_str(fetcher)} at {hex(fetcher_id)}"
        if isinstance(fetcher, AbstractFetcher) and fetcher.config_file:
            pretty += f" (file='{fetcher.config_file}')"
        return pretty

    def _child_str(self, fetcher: Fetcher[SourceType, IdType]) -> str:
        """Return ``str(fetcher)``, or its type name if that could run discovery: a custom ``__str__`` may read `sources`.

        Bundled ``__str__`` methods never run discovery.
        """
        if getattr(type(fetcher).__str__, "__module__", "").startswith("id_translation."):
            return str(fetcher)
        if isinstance(fetcher, (AbstractFetcher, MultiFetcher)):
            discovered = fetcher._placeholders is not None
        else:
            discovered = self._placeholders is not None  # Set only once every remaining child is discovered.

        return str(fetcher) if discovered else tname(type(fetcher))  # No try/catch, raising __str__() is a broken impl.

    def _discard(self, fetcher_id: int) -> None:
        pretty = self._format_child(fetcher_id)
        del self._id_to_rank[fetcher_id]
        fetcher = self._id_to_fetcher.pop(fetcher_id)
        try:
            fetcher.close()
        except Exception:
            self._logger.exception(f"Failed to close discarded {pretty}.")

    def _raise_with_notes(self, e: BaseException, fetcher: Fetcher[SourceType, IdType]) -> Never:
        e.add_note(self._context_note(fetcher))
        raise e

    def _context_note(self, fetcher: Fetcher[SourceType, IdType]) -> str:
        return f"Context (added by {type(self).__name__}):\n - child= {self.format_child(fetcher)}"

    def __setstate__(self, state: dict[str, Any]) -> None:
        # Unpickled children have new identities, and with them new `id()` keys.
        self.__dict__.update(state, **self._rekeyed(state, state["_id_to_fetcher"]))

    def __deepcopy__(self, memo: dict[int, Any] | None = None) -> Self:
        # Neither this nor pickling takes the discovery lock: copied while another thread discovers, the children dicts
        # may change mid-copy (`_discard`) and the copy raises. A Translator's copy() waits only for its own first use.
        if memo is None:
            memo = {}
        cls = self.__class__
        result = cls.__new__(cls)
        mark = len(memo)  # `deepcopy` only ever inserts into the memo, and dicts preserve insertion order.
        memo[id(self)] = result

        try:
            dicts = self._copy_dicts(memo)
            for k, v in self.__dict__.items():
                setattr(result, k, dicts[k] if k in dicts else deepcopy(v, memo))
        except Exception:
            # Leave a shared memo as we found it; a later copy must not adopt the half-built shell.
            for key in list(memo)[mark:]:
                del memo[key]
            raise

        return result

    def _copy_dicts(self, memo: dict[int, Any]) -> dict[str, dict[str, Any] | dict[int, Any]]:
        clones: dict[int, Fetcher[SourceType, IdType]] = {}
        for old_id, old_fetcher in self._id_to_fetcher.items():
            try:
                clones[old_id] = deepcopy(old_fetcher, memo)
            except TypeError as e:
                # Sharing the child instead would hand back a copy that is partly the original, with only a log line
                # to say so. Translator.copy(fetcher='auto') handles the failure for the fetcher as a whole.
                raise TypeError(f"Cannot clone {self.format_child(old_fetcher)}: {e}") from e

        return self._rekeyed(self.__dict__, clones)

    @staticmethod
    def _rekeyed(
        members: dict[str, Any], children: dict[int, Fetcher[SourceType, IdType]]
    ) -> dict[str, dict[str, Any] | dict[int, Any]]:
        """The `id()`-keyed members, keyed by `children`, which replace the old children by their old IDs."""
        new_id = {old_id: id(child) for old_id, child in children.items()}
        return {
            "_id_to_fetcher": {new_id[old_id]: child for old_id, child in children.items()},
            "_id_to_rank": {new_id[old_id]: rank for old_id, rank in members["_id_to_rank"].items()},
            "_source_to_id": {source: new_id[old_id] for source, old_id in members["_source_to_id"].items()},
        }


OSC_HELPER: LiteralHelper[OnSourceConflict] = LiteralHelper(
    OnSourceConflict,
    default_name="on_source_conflict",
    type_name="OnSourceConflict",
)


def _log_discard(
    logger: logging.LoggerAdapter[logging.Logger],
    level: int,
    child: str,
    reason: str,
    *,
    task_id: int,
    exc_info: bool = False,
    extra: dict[str, Any] | None = None,
) -> None:
    if not logger.isEnabledFor(level):
        return

    logger.log(
        level,
        f"Discarding optional {child}: {reason}",
        exc_info=exc_info,
        extra={"task_id": task_id, **(extra or {})},
    )


def _log_outranked(
    logger: logging.LoggerAdapter[logging.Logger],
    child: str,
    *,
    optional: bool,
    discard_level: int,
    task_id: int,
    discarded: dict[Any, list[str]],
) -> None:
    if not discarded:
        return  # A child without sources was logged at discovery.

    reason = "All sources found in higher-ranking fetchers."
    extra = {"discarded": [*discarded]}  # Not keyed by source: a JSON key needs str(), which may raise.
    if optional:
        _log_discard(logger, discard_level, child, reason, task_id=task_id, extra=extra)
    elif logger.isEnabledFor(logging.WARNING):
        logger.warning(f"Required {child} is useless, but will be kept: {reason}", extra={"task_id": task_id, **extra})


def _handle_conflict(
    logger: logging.LoggerAdapter[logging.Logger],
    source: Any,
    accepted: str,
    rejected: str,
    on_source_conflict: OnSourceConflict,
    *,
    task_id: int,
) -> None:
    rank_order = "Rank follows input order (in TOML: the main file, then extra_fetchers)."
    extra = {"task_id": task_id, "source": source}
    if on_source_conflict == "raise":
        msg = f"The {accepted} and the {rejected} both claim {source=}."
        hint = (
            f"{rank_order} Set on_source_conflict='warn' or 'ignore' (in TOML: [fetching.MultiFetcher]) to keep the"
            " highest-ranked claim."
        )
        logger.error(msg, extra=extra)  # The exception does not carry the task_id.
        raise exceptions.DuplicateSourceError(msg, source=source, hints=hint)

    msg = f"Discarded {source=} retrieved from {rejected} since the {accepted} already claimed same source."
    if on_source_conflict == "warn":
        logger.warning(msg, extra=extra)
        emit_warning(f"{msg}\nHint: {rank_order}", exceptions.DuplicateSourceWarning, logged=True)
    elif on_source_conflict == "ignore" and logger.isEnabledFor(logging.DEBUG):
        logger.debug(msg, extra=extra)


def _warn_dropped_translations(
    logger: logging.LoggerAdapter[logging.Logger],
    source: Any,
    *,
    returned_by: str,
    owner: str | None,
    implementation: str,
    operation: FetchOperation,
    task_id: int,
) -> None:
    belongs_to = "no fetcher" if owner is None else f"the {owner}"
    msg = (
        f"Dropping translations for {source=} returned by the {returned_by} during {operation};"
        f" this source belongs to {belongs_to}."
    )
    logger.warning(msg, extra={"task_id": task_id, "source": source})
    category = exceptions.FetcherWarning if owner is None else exceptions.DuplicateSourceWarning
    emit_warning(f"{msg}\nHint: The implementation of {implementation} may be incorrect.", category, logged=True)
