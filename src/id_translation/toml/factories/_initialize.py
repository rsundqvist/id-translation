from types import ModuleType
from typing import Any, TypeVar

from rics.misc import format_kwargs, get_by_full_name

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

    msg = (
        f"Expected an instance of '{instance_of.__name__}', but {name}({format_kwargs(kwargs)}) produced: {instance!r}"
    )
    raise TypeError(msg)
