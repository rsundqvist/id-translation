"""Generation of ID data for benchmarking.

The goal is to produce *realistic* translatable payloads cheaply (outside of the timed region) so that the
benchmark measures :meth:`id_translation.Translator.translate` and not data construction.

Two knobs shape an ID array:

* ``n`` -- the number of rows (the headline scaling axis).
* ``n_unique`` -- the *cardinality*, i.e. the number of distinct IDs. Real-world ID columns are almost always
  low-cardinality categoricals (a few thousand customers referenced by millions of orders), but high-cardinality
  (``n_unique == n``) is the pathological case for the fetch + map-building stages, so we cover both.
"""

from typing import Literal, get_args
from uuid import UUID

import numpy as np

IdType = Literal["int", "str", "uuid-str", "uuid"]
"""Supported ID dtypes.

* ``int`` / ``str`` -- native vectorized dtypes.
* ``uuid-str`` -- UUIDs stored in canonical string form (vectorized ``String``); the common way real data carries
  UUIDs, and the headline string case we track over time.
* ``uuid`` -- ``UUID`` *objects* (``object`` dtype); the slow Python path, kept for the IO investigation.
"""

ID_TYPES: tuple[IdType, ...] = get_args(IdType)

SOURCE = "source"
"""The single source/column name used throughout the suite."""

_SEED = 20190511


def make_ids(n: int, *, n_unique: int | None, id_type: IdType) -> np.ndarray:
    """Build an array of ``n`` IDs drawn from ``n_unique`` distinct values.

    Args:
        n: Number of rows.
        n_unique: Number of distinct IDs. ``None`` means "all unique" (``n_unique == n``).
        id_type: One of :data:`ID_TYPES`.

    Returns:
        A 1-D :class:`numpy.ndarray`. Integer dtype for ``int``, otherwise ``object``.
    """
    if n_unique is None or n_unique > n:
        n_unique = n
    if n_unique < 1:
        raise ValueError(f"{n_unique=} must be >= 1")

    rng = np.random.default_rng(_SEED)

    if n_unique == n:
        # Every value distinct: a shuffled range is exact and cheap.
        pool = rng.permutation(n)
    else:
        # Sample with replacement from a fixed pool to pin the cardinality.
        pool = rng.integers(0, n_unique, size=n, dtype=np.int64)

    return _as_id_type(pool, id_type)


def unique_ids(ids: np.ndarray) -> list[object]:
    """Return the distinct IDs in ``ids`` as a plain list (the fetcher's universe)."""
    # pandas/np unique sorts; order is irrelevant for the translation map.
    return list(dict.fromkeys(ids.tolist()))


def _as_id_type(values: np.ndarray, id_type: IdType) -> np.ndarray:
    if id_type == "int":
        return values.astype(np.int64)
    if id_type == "str":
        return values.astype(np.int64).astype(str).astype(object)
    if id_type == "uuid-str":
        # Canonical UUID strings (vectorized String dtype): the common "UUID stored as text" case.
        return np.array([str(UUID(int=int(v))) for v in values.tolist()], dtype=object)
    if id_type == "uuid":
        # UUID(int=...) for each distinct value; object dtype.
        return np.array([UUID(int=int(v)) for v in values.tolist()], dtype=object)
    raise ValueError(f"Unknown {id_type=}; expected one of {ID_TYPES}.")
