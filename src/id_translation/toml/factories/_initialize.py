from types import ModuleType
from typing import Any, TypeVar

from rics.misc import get_by_full_name, tname

T = TypeVar("T")


def initialize(
    name: str,
    kwargs: dict[str, Any],
    instance_of: type[T],
    default_module: ModuleType | None,
) -> T:
    cls = get_by_full_name(name, default_module)  # Or factory function.
    instance = cls(**kwargs)
    if isinstance(instance, instance_of):
        return instance

    # Name the arguments only: their values may be interpolated secrets, and so may the instance's repr.
    msg = (
        f"Expected an instance of '{instance_of.__name__}', but {name}({', '.join(kwargs)})"
        f" produced a '{tname(instance, include_module=True)}'."
    )
    raise TypeError(msg)
