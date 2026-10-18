"""Every warning in the suite derives from ``IdTranslationWarning``, so a single filter covers all of them."""

import ast
import importlib
import pkgutil
import warnings
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

import id_translation
from id_translation._utils.emit_warning import emit_warning
from id_translation.exceptions import IdTranslationWarning


def _modules() -> Iterator[ModuleType]:
    # The walk yields submodules only. It never reaches its own `onerror`: each package is imported here first.
    yield id_translation
    for info in pkgutil.walk_packages(id_translation.__path__, prefix="id_translation."):
        try:
            yield importlib.import_module(info.name)
        except Exception as e:
            pytest.fail(f"Cannot import {info.name!r} ({e!r}); the walk would silently skip any warnings it defines.")


def _warning_classes() -> list[type[Warning]]:
    found: dict[type[Warning], None] = {}
    for module in _modules():
        for obj in vars(module).values():
            if isinstance(obj, type) and issubclass(obj, Warning) and obj.__module__ == module.__name__:
                found[obj] = None
    return list(found)


def test_all_warnings_inherit_base() -> None:
    classes = _warning_classes()
    assert len(classes) > 5, "walk found too few classes; is the package layout intact?"

    outside = [f"{c.__module__}.{c.__name__}" for c in classes if not issubclass(c, IdTranslationWarning)]
    assert outside == [], "Warning(s) not derived from IdTranslationWarning:\n" + "\n".join(outside)


def test_roots_have_no_stdlib_bases() -> None:
    """A blanket ``ignore::UserWarning`` must not silence the suite; ``IdTranslationWarning`` is the only base."""
    from id_translation.exceptions import TranslationWarning
    from id_translation.fetching.exceptions import FetcherWarning
    from id_translation.mapping.exceptions import MappingWarning

    for root in (TranslationWarning, MappingWarning, FetcherWarning):
        assert root.__bases__ == (IdTranslationWarning,), root


def test_default_category_is_covered_by_base_filter() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        warnings.filterwarnings("ignore", category=IdTranslationWarning)
        emit_warning("would raise if the default category escaped the base filter")


def test_all_warnings_go_through_emit_warning() -> None:
    """A direct ``warnings.warn()`` call could pick a category outside the hierarchy; only the helper may call it."""
    src_root = Path(id_translation.__file__).parent
    helper = src_root / "_utils" / "emit_warning.py"

    direct_calls = []
    for path in sorted(src_root.rglob("*.py")):
        if path == helper:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
            if name in {"warn", "warn_explicit", "_warn"}:
                direct_calls.append(f"{path.relative_to(src_root)}:{node.lineno}")

    assert direct_calls == [], "Direct warn() calls; use emit_warning() instead:\n" + "\n".join(direct_calls)
