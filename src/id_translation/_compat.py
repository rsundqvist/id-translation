"""Vendored functions."""

from os import PathLike
from pathlib import Path
from typing import TypeAlias

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
