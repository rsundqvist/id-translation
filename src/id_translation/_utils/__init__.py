import secrets as _secrets
import shutil as _shutil
from collections.abc import Callable as _Callable
from collections.abc import Iterable as _Iterable
from pathlib import Path as _Path
from typing import IO as _IO
from typing import Any as _Any

DOC_LINK: str

__all__ = [
    "DOC_LINK",
    "add_hints",
    "replace_atomically",
    "resolve_changing_default",
    "warn_changing_default",
]


def add_hints(exc: BaseException, hints: str | _Iterable[str]) -> None:
    """Attach `hints` to `exc` as PEP 678 notes, each prefixed with ``Hint: ``."""
    for hint in (hints,) if isinstance(hints, str) else hints:
        exc.add_note(f"Hint: {hint}")


def resolve_changing_default(value: bool | None, *, owner: str, argument: str) -> bool:
    """Return `value`, or ``True`` with a ``FutureWarning`` if it was omitted: the default becomes ``False`` in 2.0."""
    if value is not None:
        return value
    warn_changing_default(owner=owner, argument=argument)
    return True


def warn_changing_default(*, owner: str, argument: str) -> None:
    """Emit the ``FutureWarning`` for an omitted `argument` whose default, ``True``, becomes ``False`` in 2.0."""
    from .emit_warning import emit_warning  # noqa: PLC0415

    emit_warning(
        f"{owner}({argument}=...) defaults to True. Pass {argument}=True to keep it, or {argument}=False as in 2.0."
        f"\nWARNING: The default changes to {argument}=False in `id-translation==2.0.0`.",
        FutureWarning,
    )


def replace_atomically(path: _Path, write: _Callable[[_IO[bytes]], _Any]) -> None:
    """Call `write` on a temporary file next to `path`, then move it into place; readers see the old file or the new.

    As when writing to `path` in place, a symbolic link's target is replaced, and a replaced file keeps its mode.
    """
    if path.is_symlink():
        path = path.resolve()
    tmp = path.with_name(f".{path.name}.{_secrets.token_hex(8)}.tmp")
    f = tmp.open("xb")  # Not mkstemp(), whose files are private (0600): the umask applies, as for open(path, "wb").
    try:
        with f:
            write(f)
        if path.exists():
            _shutil.copymode(path, tmp)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def __getattr__(name: str) -> _Any:
    if name == "DOC_LINK":
        from id_translation import __version__  # noqa: PLC0415

        def _is_release(v: str) -> bool:
            parts = v.split(".")
            return len(parts) == 3 and all(map(str.isdigit, parts))  # noqa: PLR2004

        version = f"v{__version__}" if _is_release(__version__) else "latest"

        return f"https://id-translation.readthedocs.io/en/{version}/"

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
