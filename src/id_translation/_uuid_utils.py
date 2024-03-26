from collections.abc import Sequence
from typing import Any, TypeVar
from uuid import UUID

import numpy as np

IdCollectionT = TypeVar("IdCollectionT", bound=Sequence)  # type: ignore[type-arg] # TODO: Need Higher-Kinded TypeVars


def cast_many(ids: IdCollectionT) -> IdCollectionT:
    """Cast `ids` to UUIDs."""
    uuids = map(UUID, ids)
    if isinstance(ids, np.ndarray):
        return np.fromiter(uuids, dtype=UUID)
    else:
        return type(ids)(uuids)  # type: ignore[call-arg]


def try_cast_many(ids: IdCollectionT) -> IdCollectionT:
    """Try casting `ids` to UUIDs, falling back to the original input."""
    if len(ids) == 0:
        return ids

    try:
        return cast_many(ids)
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
