"""Freeze the import graph of the lower-level modules of ``id_translation``; ``TOP`` modules are unchecked.

A new edge must be added to ``ALLOWED`` deliberately. Imports under ``TYPE_CHECKING`` and inside functions count too.
"""

import ast
from pathlib import Path

import pytest

import id_translation

PACKAGE_ROOT = Path(id_translation.__file__).parent
ROOT = "id_translation"  # The package itself, e.g. `from id_translation import __version__`.

BASE = {"_utils", "_uuid_utils", "exceptions", "logging", "types"}
# Unchecked. `_tasks` is part of the Translator implementation.
TOP = {"_tasks", "_translator", "testing", "toml", "translator_typing", "utils", ROOT}

# Units other than BASE that each unit may import. BASE units may import each other.
ALLOWED: dict[str, set[str]] = {
    "mapping": set(),
    "transform": set(),
    "offline": {"transform"},
    "dio": {"offline"},
    "fetching": {"mapping", "offline", "transform"},
    **{unit: set() for unit in BASE},
}

EXCEPTIONS = {
    ("_utils/__init__.py", ROOT),
    ("_utils/emit_warning.py", ROOT),
    ("transform/_impl/bitmask.py", "offline"),
}


def _unit(path: Path) -> str:
    return path.relative_to(PACKAGE_ROOT).with_suffix("").parts[0]


def _target_unit(module: str) -> str | None:
    parts = module.split(".")
    if parts[0] != ROOT:
        return None
    if len(parts) == 1:
        return ROOT
    is_module = (PACKAGE_ROOT / parts[1]).is_dir() or (PACKAGE_ROOT / f"{parts[1]}.py").is_file()
    return parts[1] if is_module else ROOT


def _imported_units(path: Path) -> set[str]:
    parts = path.relative_to(PACKAGE_ROOT.parent).with_suffix("").parts
    package = ".".join(parts[:-1])  # For __init__.py, the package itself.

    modules: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), str(path))):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
            module = (f"{base}.{node.module}" if node.module else base) if node.level else (node.module or "")
            if module == ROOT:  # `from id_translation import x` may import a submodule or a package attribute.
                modules.extend(f"{module}.{alias.name}" for alias in node.names)
            else:
                modules.append(module)

    return {unit for module in modules if (unit := _target_unit(module)) is not None}


def _units() -> set[str]:
    return {_unit(path) for path in PACKAGE_ROOT.rglob("*.py")} - {"__init__"} | {ROOT}


def test_every_unit_is_classified():
    assert _units() == set(ALLOWED) | TOP


@pytest.mark.parametrize("unit", sorted(ALLOWED))
def test_imports(unit):
    root = PACKAGE_ROOT / unit
    paths = sorted(root.rglob("*.py")) if root.is_dir() else [PACKAGE_ROOT / f"{unit}.py"]
    allowed = ALLOWED[unit] | BASE | {unit}

    violations = sorted(
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}: {target}"
        for path in paths
        for target in _imported_units(path) - allowed
        if (path.relative_to(PACKAGE_ROOT).as_posix(), target) not in EXCEPTIONS
    )
    assert not violations
