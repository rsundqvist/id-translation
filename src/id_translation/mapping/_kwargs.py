import inspect
from collections.abc import Callable, Mapping
from typing import Any

from rics.misc import tname


def check_function_kwargs(func: Callable[..., Any], kwargs: Mapping[str, Any], *, what: str) -> None:
    """Raise now for keyword arguments that `func` does not take, rather than at its first call.

    Value, candidates and context are passed positionally; keyword arguments the caller adds later (e.g. through
    ``Mapper.apply(**kwargs)``) are not known yet, so only unexpected names are reported, not missing ones.
    """
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return  # Builtins and some callables have no inspectable signature; they are checked when called.

    try:
        signature.bind_partial(None, None, None, **kwargs)
    except TypeError as e:
        msg = f"Bad {what} arguments {dict(kwargs)} for {tname(func, include_module=True)}{signature}: {e}"
        raise TypeError(msg) from e
