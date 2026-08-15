"""Enforce that raised exceptions attach hints via `add_note()`/`hints=`, not by baking them into the message.

`add_note()` is required specifically because it is raised: `warnings.warn()` silently drops `__notes__`, so a
warning's message is the one legitimate place a "Hint: ..." string may still be baked in directly.
"""

import ast
import re
from pathlib import Path

_HINT_VAR_NAMES = {"hint", "hints"}
_HINT_WORD = re.compile(r"\bhints?\b", re.IGNORECASE)


def _contains_hint_text(node: ast.AST) -> bool:
    return any(
        isinstance(sub, ast.Constant) and isinstance(sub.value, str) and "Hint:" in sub.value for sub in ast.walk(node)
    )


def _references_hint_var(node: ast.AST) -> bool:
    """True if `node` reads a variable named `hint`/`hints` -- the tell for a hint folded into a message inline."""
    return any(
        isinstance(sub, ast.Name) and sub.id in _HINT_VAR_NAMES and isinstance(sub.ctx, ast.Load)
        for sub in ast.walk(node)
    )


def _add_note_call_subtrees(func: ast.FunctionDef) -> set[ast.AST]:
    covered: set[ast.AST] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_note":
            covered.update(ast.walk(node))
    return covered


def _is_super_init_call(call: ast.Call) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "__init__"
        and isinstance(func.value, ast.Call)
        and isinstance(func.value.func, ast.Name)
        and func.value.func.id == "super"
    )


def _update_known(stmt: ast.stmt, known_calls: dict[str, ast.Call], known_hints: dict[str, bool]) -> None:
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
        name = stmt.targets[0].id
        if isinstance(stmt.value, ast.Call):
            known_calls[name] = stmt.value
            known_hints[name] = False
        else:
            known_calls.pop(name, None)
            known_hints[name] = _contains_hint_text(stmt.value) or _references_hint_var(stmt.value)
    elif isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Name):
        name = stmt.target.id
        known_hints[name] = (
            known_hints.get(name, False) or _contains_hint_text(stmt.value) or _references_hint_var(stmt.value)
        )


def _raise_target_call(stmt: ast.Raise, known_calls: dict[str, ast.Call]) -> ast.Call | None:
    if isinstance(stmt.exc, ast.Call):
        return stmt.exc
    if isinstance(stmt.exc, ast.Name):
        return known_calls.get(stmt.exc.id)
    return None


def _arg_bakes_hint(arg: ast.expr, known_hints: dict[str, bool]) -> bool:
    if _contains_hint_text(arg) or _references_hint_var(arg):
        return True
    return isinstance(arg, ast.Name) and known_hints.get(arg.id, False)


def _call_bakes_hint(call: ast.Call, known_hints: dict[str, bool]) -> bool:
    for arg in call.args:
        if _arg_bakes_hint(arg, known_hints):
            return True
    for kw in call.keywords:
        if kw.arg == "hints":  # The sanctioned way to attach hints -- not a violation.
            continue
        if kw.value is not None and _arg_bakes_hint(kw.value, known_hints):
            return True
    return False


def _child_blocks(stmt: ast.stmt) -> list[list[ast.stmt]]:
    blocks = [getattr(stmt, field) for field in ("body", "orelse", "finalbody") if getattr(stmt, field, None)]
    blocks.extend(handler.body for handler in getattr(stmt, "handlers", []))
    return blocks


def _flagged_call(stmt: ast.stmt, known_calls: dict[str, ast.Call]) -> ast.Call | None:
    if isinstance(stmt, ast.Raise) and stmt.exc is not None:
        return _raise_target_call(stmt, known_calls)
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and _is_super_init_call(stmt.value):
        return stmt.value
    return None


def _scan_block(
    stmts: list[ast.stmt], known_calls: dict[str, ast.Call], known_hints: dict[str, bool], covered: set[ast.AST]
) -> list[int]:
    known_calls = dict(known_calls)
    known_hints = dict(known_hints)
    violations = []

    for stmt in stmts:
        _update_known(stmt, known_calls, known_hints)

        call = _flagged_call(stmt, known_calls)
        if call is not None and call not in covered and _call_bakes_hint(call, known_hints):
            violations.append(stmt.lineno)

        for block in _child_blocks(stmt):
            violations.extend(_scan_block(block, known_calls, known_hints, covered))

    return violations


def _function_violations(func: ast.FunctionDef) -> list[int]:
    covered = _add_note_call_subtrees(func)
    return _scan_block(func.body, {}, {}, covered)


def _collect_violations(src_root: Path) -> list[str]:
    violations: list[str] = []

    for path in sorted(src_root.rglob("*.py")):
        # Default locale encoding isn't UTF-8 on Windows; breaks with non-ASCII docstrings (e.g. emoji in logging.py).
        source = path.read_text(encoding="utf-8")
        if not _HINT_WORD.search(source):
            continue

        tree = ast.parse(source, filename=str(path))
        rel = path.relative_to(src_root.parent)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                violations.extend(
                    f"{rel}:{lineno}: `{node.name}()` bakes a hint into the exception message;"
                    f" use add_note(...)/hints=... instead"
                    for lineno in _function_violations(node)
                )

    return violations


def test_exception_classes_use_add_note_for_hints() -> None:
    import id_translation

    src_root = Path(id_translation.__file__).parent
    violations = _collect_violations(src_root)
    assert not violations, "Found hint(s) not attached via add_note()/hints=:\n" + "\n".join(violations)
