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
