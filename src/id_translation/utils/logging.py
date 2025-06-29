"""Logging utilities."""

import typing as _t
from uuid import UUID as _UUID


def cast_unsafe(obj: _t.Any) -> _t.Any:
    """Attempt to cast an arbitrary object to a JSON-safe type."""
    formatters: dict[type[_t.Any], _t.Any] = {
        _UUID: str,
        list: lambda x: [cast_unsafe(obj) for obj in x],
    }

    try:
        import numpy as np

        formatters[np.integer] = int
        formatters[np.floating] = float
        formatters[np.ndarray] = np.ndarray.tolist
    except ImportError:
        pass

    for clazz, formatter in formatters.items():
        if isinstance(obj, clazz):
            return formatter(obj)
    return obj
