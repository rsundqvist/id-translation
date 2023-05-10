from typing import Any, Sequence, TypeVar
from uuid import UUID

IdCollectionT = TypeVar("IdCollectionT", bound=Sequence)  # type: ignore[type-arg] # TODO: Need Higher-Kinded TypeVars


def cast_many(ids: IdCollectionT) -> IdCollectionT:
    """Cast `ids` to UUIDs."""
    uuids = ids if isinstance(ids[0], UUID) else map(UUID, ids)
    return type(ids)(map(str, uuids))  # type: ignore


def try_cast_many(ids: IdCollectionT) -> IdCollectionT:
    """Try casting `ids` to UUIDs, falling back to the original input."""
    if not ids:
        return ids

    try:
        return cast_many(ids)
    except (ValueError, AttributeError, TypeError):
        return ids


def try_cast_one(idx: Any) -> Any:
    """Try casting `idx` to a UUID, falling back to the original input."""
    try:
        if not isinstance(idx, UUID):
            idx = UUID(idx)
        return str(idx)
    except (ValueError, AttributeError, TypeError):
        return idx
