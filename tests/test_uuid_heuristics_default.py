"""``enable_uuid_heuristics`` is opt-in everywhere, so no entry point needs remembering as the exception."""

import importlib
import inspect
import pkgutil
from collections.abc import Callable, Iterator
from typing import Any

import pytest

import id_translation


def _functions() -> Iterator[tuple[str, Callable[..., Any]]]:
    for info in pkgutil.walk_packages(id_translation.__path__, prefix="id_translation."):
        try:
            module = importlib.import_module(info.name)
        except Exception as e:
            pytest.fail(f"Cannot import {info.name!r} ({e!r}); the walk would silently skip its functions.")
        for name, obj in vars(module).items():
            if getattr(obj, "__module__", None) != module.__name__:
                continue
            if inspect.isfunction(obj):
                yield f"{module.__name__}.{name}", obj
            elif inspect.isclass(obj):
                for attr, member in vars(obj).items():
                    if inspect.isfunction(member):
                        yield f"{module.__name__}.{name}.{attr}", member


def test_defaults_to_false() -> None:
    found = []
    wrong = []
    for qualname, func in _functions():
        parameter = inspect.signature(func).parameters.get("enable_uuid_heuristics")
        if parameter is None or parameter.default is inspect.Parameter.empty:
            continue
        found.append(qualname)
        if parameter.default is not False:
            wrong.append(f"{qualname}: {parameter.default!r}")

    assert len(found) > 5, "walk found too few defaults; is the package layout intact?"
    assert wrong == [], "enable_uuid_heuristics must default to False:\n" + "\n".join(wrong)
