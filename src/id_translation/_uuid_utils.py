from collections.abc import Sequence
from typing import Any
from uuid import UUID


def try_cast_many(ids: Sequence[Any]) -> Sequence[Any]:
    """Try casting `ids` to UUIDs, falling back to the original input."""
    if len(ids) == 0:
        return ids

    try:
        return list(map(UUID, ids))
    except (ValueError, AttributeError, TypeError):
        return ids


def try_cast_one(idx: Any) -> Any:
    """Try casting `idx` to a UUID, falling back to the original input."""
    if isinstance(idx, UUID):
        return idx

    try:
        return UUID(idx)
    except (ValueError, AttributeError, TypeError):
        return idx
