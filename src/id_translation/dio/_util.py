from typing import Any

from rics.misc import tname


def pretty_io_name(arg: Any) -> str:
    """Pretty-print IO name."""
    return tname(arg, prefix_classname=True, include_module=True)
