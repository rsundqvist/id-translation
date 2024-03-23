"""Logging utilities."""

import typing as _t
from uuid import UUID as _UUID

import numpy as _np


def cast_unsafe(obj: _t.Any) -> _t.Any:
    """Attempt to cast an arbitrary object to a JSON-safe type."""
    for clazz, formatter in FORMATTERS.items():
        if isinstance(obj, clazz):
            return formatter(obj)
    return obj


FORMATTERS: _t.Dict[_t.Type[_t.Any], _t.Any] = {
    _UUID: str,
    _np.integer: int,
    _np.floating: float,
    _np.ndarray: _np.ndarray.tolist,
    list: lambda x: [cast_unsafe(obj) for obj in x],
}
"""Formatters used to cast unsafe JSON types."""
