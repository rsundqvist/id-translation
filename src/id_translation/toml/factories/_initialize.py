from types import ModuleType
from typing import Any, TypeVar

from rics.misc import get_by_full_name, tname

from ..._utils import type_name
from ..exceptions import ConfigFileError

T = TypeVar("T")


def initialize(
    name: str,
    kwargs: dict[str, Any],
    instance_of: type[T],
    default_module: ModuleType | None,
    *,
    hint: str | None = None,
) -> T:
    try:
        cls = get_by_full_name(name, default_module)  # Or factory function.
    except Exception as e:
        # The section key names something that does not exist, or whose module cannot be imported. Errors from the
        # object itself, below, are its own.
        raise ConfigFileError(f"Cannot resolve '{name}': {type(e).__name__}: {e}") from e
    if not callable(cls):
        raise ConfigFileError(f"Cannot resolve '{name}': a '{type_name(cls)}' is not callable.")

    instance = cls(**kwargs)
    if isinstance(instance, instance_of):
        return instance

    # Name the arguments only: their values may be interpolated secrets, and so may the instance's repr.
    msg = (
        f"Expected an instance of '{instance_of.__name__}', but {name}({', '.join(kwargs)})"
        f" produced a '{tname(instance, include_module=True)}'."
    )
    raise ConfigFileError(msg, hints=hint or f"Subclass {instance_of.__name__}.")


def expect_table(value: Any, toml_path: str) -> None:
    if not isinstance(value, dict):
        raise ConfigFileError(f"[{toml_path}] must be a table, not {type(value).__name__}.")
