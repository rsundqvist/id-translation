"""Utilities for emitting warnings with accurate stack levels."""

_USER_PREFIXES: set[str] = set()


def add_skip_file_prefix(path: str) -> None:
    """Register a file path prefix to be skipped during warning emission."""
    _USER_PREFIXES.add(path)


def emit_warning(msg: str, category: type[Warning] = UserWarning) -> None:
    """Emit warning with automatic stack level."""
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
