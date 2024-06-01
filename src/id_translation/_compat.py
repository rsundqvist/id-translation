"""Vendored functions."""

from functools import wraps
from os import PathLike
from pathlib import Path
from typing import Callable, ParamSpec, TypeAlias, TypeVar
from warnings import warn

from rics.misc import tname

# TODO(0.11.0): any_path_to_path(p, postprocessor=...)
PathLikeType: TypeAlias = str | PathLike[str] | Path


try:
    from rics import strings

    fmt_perf = strings.format_perf_counter
    fmt_sec = strings.format_seconds
except ImportError:
    from rics import performance

    # TODO(0.11.0): Drop this.
    fmt_perf = performance.format_perf_counter
    fmt_sec = performance.format_seconds


P = ParamSpec("P")
T = TypeVar("T")

PARAMS = (
    ("copy", "inplace"),
    ("max_fails", "maximal_untranslated_fraction"),
)
WARNED: set[str] = set()  # Minimize the amount of warnings - once per param is enough.


def deprecated_params(__func: Callable[P, T], /) -> Callable[P, T]:
    @wraps(__func)
    def wrap(*args: P.args, **kwargs: P.kwargs) -> T:
        for new, old in PARAMS:
            if old in kwargs:
                if new in kwargs:
                    name = tname(__func, prefix_classname=True)
                    msg = f"Ambiguous call: {name}() does not accept both `{old}` and `{new}`."
                    raise TypeError(msg)

                if old not in WARNED:
                    WARNED.add(old)

                    name = tname(__func, prefix_classname=True)
                    msg = f"{name}(): The `{old}` parameter is deprecated; use `{new}` instead."
                    warn(message=msg, category=DeprecationWarning, stacklevel=2)

                value = kwargs.pop(old)

                if old == "inplace":
                    value = not value

                kwargs[new] = value

        return __func(*args, **kwargs)

    return wrap
