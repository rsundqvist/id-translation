"""Utilities for emitting warnings with accurate stack levels."""

from id_translation import logging as _logging

_USER_PREFIXES: set[str] = set()


def add_skip_file_prefix(path: str) -> None:
    """Add a path to skip in warnings.

    Useful e.g. for internal libraries that are based on the https://github.com/rsundqvist/id-translation-project/
    template.

    Args:
        path: Path to add.

    See Also:
         * The :attr:`~id_translation.logging.EMIT_LOGGED_WARNINGS` attribute.
         * The :py:func:`warnings.warn(skip_file_prefixes=...) <warnings.warn>` function.
    """
    _USER_PREFIXES.add(path)


def emit_warning(
    msg: str | Warning,
    category: type[Warning] = UserWarning,
    logged: bool = False,
) -> None:
    """Emit warning with automatic stack level."""
    if logged and not _logging.EMIT_LOGGED_WARNINGS:
        return

    import sys  # noqa: PLC0415
    from warnings import warn  # noqa: PLC0415

    if sys.version_info >= (3, 12):
        warn(msg, category, skip_file_prefixes=_get_package_dirs())
    else:
        warn(msg, category, stacklevel=_find_stack_level())


def _find_stack_level() -> int:
    """Stolen from Pandas."""
    import inspect  # noqa: PLC0415

    # https://stackoverflow.com/questions/17407119/python-inspect-stack-is-slow
    frame = inspect.currentframe()
    try:
        n = 0
        while frame:
            filename = inspect.getfile(frame)
            if filename.startswith(_get_package_dirs()):
                frame = frame.f_back
                n += 1
            else:
                break
    finally:
        # See https://docs.python.org/3/library/inspect.html#inspect.Traceback
        del frame
    return n or 1


def _get_package_dirs() -> tuple[str, ...]:
    from pathlib import Path  # noqa: PLC0415

    from id_translation import __file__  # noqa: PLC0415

    assert __file__, "id_translation.__file__ is None"  # noqa: S101
    return str(Path(__file__).parent), *_USER_PREFIXES
