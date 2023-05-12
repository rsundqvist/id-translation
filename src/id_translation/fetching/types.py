"""Types related to translation fetching."""

from dataclasses import dataclass as _dataclass
from typing import Generic as _Generic, Optional, Set

from ..offline.types import PlaceholdersTuple
from ..types import IdType, SourceType


@_dataclass(frozen=True)
class IdsToFetch(_Generic[SourceType, IdType]):
    """A source and the IDs to fetch from it."""

    source: SourceType
    """Where to fetch from."""
    ids: Set[IdType]
    """Unique IDs to fetch translations for.``"""


@_dataclass(frozen=True)
class FetchInstruction(_Generic[SourceType, IdType]):
    """Instructions passed from an ``AbstractFetcher`` to an implementation."""

    source: SourceType
    """Where to fetch from."""
    placeholders: PlaceholdersTuple
    """All desired placeholders in preferred order."""
    required: Set[str]
    """Placeholders that must be included in the response."""
    ids: Optional[Set[IdType]]
    """Unique IDs to fetch translations for. Fetch as much as possible if ``None``."""

    @property
    def fetch_all(self) -> bool:
        """Flag indicated that as much data as possible should be retrieved."""
        return self.ids is None
