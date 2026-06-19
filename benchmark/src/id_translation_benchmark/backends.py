"""Container backends -- the *types* that wrap an ID array before translation.

The headline use-case is **large datasets with vectorized types**, so the first-class backends are the
pandas and polars containers. The Python builtins (``list``/``tuple``/``dict``/``set``) are kept as a
non-vectorized baseline -- useful to show the speedup, but not the point.

Every backend exposes the same shape: build a container from a numpy ID array, and let the shared
:class:`id_translation.Translator` translate it via ``translate(container, names=SOURCE)``.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .data import SOURCE


@dataclass(frozen=True)
class Backend:
    """A way to wrap IDs in a concrete container type."""

    name: str
    build: Callable[[np.ndarray], object]
    vectorized: bool

    def __str__(self) -> str:
        return self.name


def _pandas_series(ids: np.ndarray) -> object:
    import pandas as pd

    return pd.Series(ids, name=SOURCE, copy=False)


def _pandas_index(ids: np.ndarray) -> object:
    import pandas as pd

    return pd.Index(ids, name=SOURCE)


def _pandas_frame(ids: np.ndarray) -> object:
    import pandas as pd

    return pd.DataFrame({SOURCE: ids}, copy=False)


def _polars_series(ids: np.ndarray) -> object:
    import polars as pl

    return pl.Series(SOURCE, ids)


def _polars_frame(ids: np.ndarray) -> object:
    import polars as pl

    return pl.DataFrame({SOURCE: ids})


def _py_list(ids: np.ndarray) -> object:
    return ids.tolist()


def _py_tuple(ids: np.ndarray) -> object:
    return tuple(ids.tolist())


def _py_dict(ids: np.ndarray) -> object:
    return {SOURCE: ids.tolist()}


def _py_set(ids: np.ndarray) -> object:
    # NOTE: a set collapses duplicates, so its effective size is the cardinality, not ``n``.
    return set(ids.tolist())


_ALL: tuple[Backend, ...] = (
    Backend("pandas.Series", _pandas_series, vectorized=True),
    Backend("pandas.Index", _pandas_index, vectorized=True),
    Backend("pandas.DataFrame", _pandas_frame, vectorized=True),
    Backend("polars.Series", _polars_series, vectorized=True),
    Backend("polars.DataFrame", _polars_frame, vectorized=True),
    Backend("list", _py_list, vectorized=False),
    Backend("tuple", _py_tuple, vectorized=False),
    Backend("dict", _py_dict, vectorized=False),
    Backend("set", _py_set, vectorized=False),
)

BACKENDS: dict[str, Backend] = {b.name: b for b in _ALL}
"""All known backends, keyed by name."""

VECTORIZED: list[str] = [b.name for b in _ALL if b.vectorized]
"""Names of the vectorized (pandas/polars) backends -- the headline group."""

BASELINE: list[str] = [b.name for b in _ALL if not b.vectorized]
"""Names of the non-vectorized builtin backends -- the bonus baseline group."""
