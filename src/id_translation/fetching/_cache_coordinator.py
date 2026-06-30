"""The :class:`.CacheAccess` integration for :class:`.AbstractFetcher`.

:class:`CacheCoordinator` owns the cache flow (load dispatch, complement fetch, merge, store). The fetcher composes one
and passes itself, so the coordinator can invoke the fetcher primitives ``_make_fetch_instruction`` and
``_call_user_impl`` directly. The stateless helpers :func:`covered_ids`, :func:`merge` and :func:`normalize` are its
building blocks.
"""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Generic

from ..offline.types import PlaceholderAttributes, PlaceholdersTuple, PlaceholderTranslations
from ..types import ID, IdType, SourceType
from . import exceptions
from ._cache_access import CacheAccess
from .types import FetchInstruction, PartialCacheHit

if TYPE_CHECKING:
    from ._abstract_fetcher import AbstractFetcher


class NoopCacheAccess(CacheAccess[Any, Any]):
    """A disabled :class:`.CacheAccess`; the default when a fetcher has no caching configured."""

    @property
    def enabled(self) -> bool:
        return False

    def _raise(self, *_: Any, **__: Any) -> None:
        raise NotImplementedError

    store = _raise
    load = _raise


_NOOP_CACHE_ACCESS: NoopCacheAccess = NoopCacheAccess()


class CacheCoordinator(Generic[SourceType, IdType]):
    """Runs the cache flow for an :class:`.AbstractFetcher`: load -> (hit | miss | partial) -> merge/store.

    Holds the owning fetcher so it can perform the mapping-coupled steps (fetch + normalize + complement) directly,
    keeping the placeholder-mapping logic on the fetcher.
    """

    def __init__(
        self,
        fetcher: "AbstractFetcher[SourceType, IdType]",
        cache_access: CacheAccess[SourceType, IdType] | None,
    ) -> None:
        self._fetcher = fetcher
        self._cache = _NOOP_CACHE_ACCESS if cache_access is None else cache_access

    @property
    def cache_access(self) -> CacheAccess[SourceType, IdType]:
        if self._cache is _NOOP_CACHE_ACCESS:
            raise exceptions.CacheAccessNotAvailableError("No CacheAccess configured.")

        return self._cache

    def run(
        self,
        instr: FetchInstruction[SourceType, IdType],
        placeholders: PlaceholdersTuple,
        *,
        reverse_mappings: dict[str, str],
        required_placeholders: set[str],
        placeholder_attributes: PlaceholderAttributes | None,
    ) -> PlaceholderTranslations[SourceType]:
        """Resolve `instr` against the cache, fetching only what is missing (via the owning fetcher)."""
        fetcher = self._fetcher
        cache = self._cache
        logger = fetcher.logger if cache.enabled and fetcher.logger.isEnabledFor(logging.DEBUG) else None

        def log(msg: str, event: str) -> None:
            if logger is not None:
                pretty = f"{type(cache).__name__}[source={instr.source!r}]"
                extra = {"source": instr.source, "task_id": instr.task_id, "cache_event": event}
                logger.debug(msg.format(pretty), extra=extra)

        result = cache.load(instr) if cache.enabled else None

        if isinstance(result, PartialCacheHit):
            return self._complete_partial(
                result,
                instr,
                placeholders,
                reverse_mappings=reverse_mappings,
                required_placeholders=required_placeholders,
                placeholder_attributes=placeholder_attributes,
                log=log,
            )

        if result is not None:
            log(f"{{}}.load() returned {len(result.records)} IDs.", "hit")
            return _normalize(result, reverse_mappings)

        log("{}.load() returned None.", "miss")
        translations = _normalize(fetcher._call_user_impl(instr), reverse_mappings)
        if cache.enabled:
            log(f"Calling {{}}.store() with {len(translations.records)} IDs.", "store")
            cache.store(instr, translations)
        return translations

    def _complete_partial(
        self,
        hit: PartialCacheHit[SourceType, IdType],
        instr: FetchInstruction[SourceType, IdType],
        placeholders: PlaceholdersTuple,
        *,
        reverse_mappings: dict[str, str],
        required_placeholders: set[str],
        placeholder_attributes: PlaceholderAttributes | None,
        log: Callable[[str, str], None],
    ) -> PlaceholderTranslations[SourceType]:
        if instr.ids is None:
            msg = f"{type(self._cache).__name__}.load() returned a PartialCacheHit for a fetch-all instruction."
            raise exceptions.FetcherError(msg)

        cached = hit.translations
        covered = _covered_ids(hit)
        missing = instr.ids - covered
        log(f"{{}}.load() partial hit: covered {len(covered)}/{len(instr.ids)}, fetching {len(missing)}.", "partial")
        if not missing:
            return _normalize(cached, reverse_mappings)

        # Widen the complement to the cache's layout so the merged result (and store) stays cohesive.
        if set(hit.placeholders) >= set(placeholders):
            layout = hit.placeholders
        else:
            layout = tuple(dict.fromkeys((*placeholders, *hit.placeholders)))

        fetched, complement_instr = self._fetch_complement(
            instr.source,
            layout,
            ids=missing,
            required_placeholders=set(required_placeholders),
            placeholder_attributes=placeholder_attributes,
            task_id=instr.task_id,
            enable_uuid_heuristics=instr.enable_uuid_heuristics,
        )
        log(f"Calling {{}}.store() with {len(fetched.records)} IDs.", "store")
        self._cache.store(complement_instr, fetched)

        if len(cached.records) == 0:  # `not records` is ambiguous for e.g. numpy arrays.
            return fetched

        return _merge(_normalize(cached, reverse_mappings), fetched)

    def _fetch_complement(
        self,
        source: SourceType,
        layout: PlaceholdersTuple,
        *,
        ids: set[IdType],
        required_placeholders: set[str],
        placeholder_attributes: PlaceholderAttributes | None,
        task_id: int,
        enable_uuid_heuristics: bool,
    ) -> tuple[PlaceholderTranslations[SourceType], FetchInstruction[SourceType, IdType]]:
        """Fetch and normalize the missing IDs at `layout`, returning the result and the instruction used."""
        reverse_mappings, instr = self._fetcher._make_fetch_instruction(
            source,
            layout,
            required_placeholders=required_placeholders,
            placeholder_attributes=placeholder_attributes,
            ids=ids,
            task_id=task_id,
            enable_uuid_heuristics=enable_uuid_heuristics,
        )

        translations = self._fetcher._call_user_impl(instr)
        return _normalize(translations, reverse_mappings), instr


def _covered_ids(hit: PartialCacheHit[SourceType, IdType]) -> set[IdType]:
    """Return the requested IDs a partial hit satisfies: the rows it holds, plus any it explicitly vouches for."""
    rows = hit.translations
    covered = {row[rows.id_pos] for row in rows.records}
    if hit.covered:
        covered = covered | hit.covered
    return covered


def _merge(
    cached: PlaceholderTranslations[SourceType],
    fetched: PlaceholderTranslations[SourceType],
) -> PlaceholderTranslations[SourceType]:
    """Concatenate the cached and freshly-fetched rows of a partial hit (same source and layout)."""
    if cached.placeholders != fetched.placeholders:
        msg = (
            f"Cannot merge partial cache hit for {fetched.source!r}: cached layout {cached.placeholders} does not "
            f"match fetched layout {fetched.placeholders}. A cache must return rows covering the requested layout."
        )
        raise exceptions.FetcherError(msg)

    return PlaceholderTranslations(
        source=fetched.source,
        placeholders=fetched.placeholders,
        records=[*cached.records, *fetched.records],
        id_pos=fetched.id_pos,
        placeholder_aliases={**cached.placeholder_aliases, **fetched.placeholder_aliases},
    )


def _normalize(
    translations: PlaceholderTranslations[SourceType],
    reverse_mappings: dict[str, str],
) -> PlaceholderTranslations[SourceType]:
    """Map fetched placeholders back to wanted names and (re)compute :attr:`~.PlaceholderTranslations.id_pos`."""
    if reverse_mappings:
        # The mapping is only in reverse from the Fetcher's point-of-view; we're mapping back to "proper" values.
        translations.placeholders = tuple(reverse_mappings.get(p, p) for p in translations.placeholders)

    try:
        translations.id_pos = translations.placeholders.index(ID)
    except ValueError:
        # No placeholder mapped to "id" for this source. Rely on AbstractFetcher._verify_placeholders to raise.
        translations.id_pos = -1

    translations.placeholder_aliases.update(reverse_mappings)
    return translations
