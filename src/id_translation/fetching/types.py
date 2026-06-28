"""Types related to translation fetching."""

import typing as _t
from dataclasses import dataclass as _dataclass

from .. import types as _tt
from ..offline import types as _ot


@_dataclass(frozen=True)
class IdsToFetch(_t.Generic[_tt.SourceType, _tt.IdType]):
    """A source and the IDs to fetch from it."""

    source: _tt.SourceType
    """Where to fetch from."""
    ids: set[_tt.IdType]
    """Unique IDs to fetch translations for."""


@_dataclass(frozen=True)
class FetchInstruction(_t.Generic[_tt.SourceType, _tt.IdType]):
    """Instructions passed from an ``AbstractFetcher`` to an implementation."""

    source: _tt.SourceType
    """Where to fetch from."""
    placeholders: _ot.PlaceholdersTuple
    """All desired placeholders in preferred order."""
    required: set[str]
    """Placeholders that must be included in the response."""
    placeholder_attributes: _ot.PlaceholderAttributes
    """See :attr:`.Format.placeholder_attributes` for details."""
    ids: set[_tt.IdType] | None
    """Unique IDs to fetch translations for."""
    task_id: int
    """Used for logging purposes."""
    enable_uuid_heuristics: bool
    """Improves matching when :py:class:`~uuid.UUID`-like IDs are in use.

    Implementations which have no UUID heuristics may silently ignore this flag.
    """

    @property
    def fetch_all(self) -> bool:
        """If ``True``, retrieve all available data."""
        return self.ids is None


@_dataclass(frozen=True)
class PartialCacheHit(_t.Generic[_tt.SourceType, _tt.IdType]):
    """Partial result of :meth:`.CacheAccess.load`: cached rows plus the IDs the cache vouches for.

    .. attention::

       Not supported for :attr:`.FetchInstruction.fetch_all` instructions.

    Returning this -- instead of a full :class:`.PlaceholderTranslations` (complete hit) or ``None`` (miss) -- tells the
    :class:`.AbstractFetcher` to fetch only the *missing* IDs and merge them with `translations`.
    """

    translations: _ot.PlaceholderTranslations[_tt.SourceType]
    """Cached :class:`.PlaceholderTranslations`, scoped to the requested IDs.

    May be empty (length of :attr:`.PlaceholderTranslations.records` is 0) to enforce layout; see :attr:`placeholders`.
    """

    covered: set[_tt.IdType] | None = None
    """Requested IDs the cache is satisfying.

    Defaults to the IDs present in :attr:`translations` (extracted by the fetcher); set this only to *additionally*
    vouch for IDs that have no row, e.g. known-missing IDs for negative caching.
    """

    @property
    def placeholders(self) -> _ot.PlaceholdersTuple:
        """Layout to fetch the missing IDs with; a thin alias of ``translations.placeholders``.

        .. hint::

           Use the :attr:`.CacheAccess.parent` to access e.g. available placeholders.

        The fetcher fetches the complement using at least these placeholders, so a cache keeps its stored layout
        cohesive (avoiding a per-request layout split) simply by returning that layout here -- even when `translations`
        has no rows.
        """
        return self.translations.placeholders


FetchOperation = _t.Literal["FETCH", "FETCH_ALL"]
"""Key operation types for fetching."""
Operation = _t.Literal["INITIALIZE_SOURCES"] | FetchOperation
"""Key operation types for fetchers."""
