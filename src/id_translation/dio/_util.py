from collections.abc import Iterable
from typing import Any

from rics.misc import tname

from .._utils import type_name


def pretty_io_name(arg: Any) -> str:
    """Pretty-print IO name."""
    return tname(arg, prefix_classname=True, include_module=True)


def require_names(available: Iterable[Any], names: Iterable[Any], translatable: Any) -> None:
    """Raise if any of `names` is not among the `available` keys or columns of `translatable`.

    Only for data whose names are keys, such as a ``dict`` or ``DataFrame``. The names of positional data are
    whatever the caller says they are.
    """
    present = set(available)
    if missing := [name for name in names if name not in present]:
        from id_translation.exceptions import MissingNamesError  # noqa: PLC0415

        raise MissingNamesError(
            f"Names {missing} are not in the {type_name(translatable)}-type data.",
            missing=missing,
            hints=f"Available names: {list(available)}.",
        )
