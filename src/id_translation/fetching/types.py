"""Types related to translation fetching."""

from dataclasses import dataclass
from typing import Generic, Iterable, Optional, Set

from ..offline.types import PlaceholdersTuple
from ..types import IdType, SourceType


@dataclass(frozen=True)
class IdsToFetch(Generic[SourceType, IdType]):
    """A source and the IDs to fetch from it."""

    source: SourceType
    """Where to fetch from."""
    ids: Optional[Iterable[IdType]]
    """Unique IDs to fetch translations for. Fetch as much as possible if ``None``"""


@dataclass(frozen=True)
class FetchInstruction(IdsToFetch[SourceType, IdType]):
    """Instructions passed from an ``AbstractFetcher`` to an implementation."""

    placeholders: PlaceholdersTuple
    """All desired placeholders in preferred order."""
    required: Set[str]
    """Placeholders that must be included in the response."""
    all_placeholders: bool
    """Flag indicated whether to retrieve as many placeholders as possible."""
