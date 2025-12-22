"""Logging utilities; see :doc:`/documentation/translation-logging` for help."""

import logging as _l
import typing as _t
from random import Random as _Random
from time import perf_counter as _perf_counter

from rics.env import read as _env

ENABLE_VERBOSE_LOGGING: bool = _env.read_bool("ID_TRANSLATION_VERBOSE")
"""Set to enable additional ``DEBUG``-level messages.

The default (``False``) is controlled by the :envvar:`ID_TRANSLATION_VERBOSE` variable. Use
:func:`enable_verbose_debug_messages` to enable temporarily.
"""

LOGGER = _l.getLogger("id_translation")
"""Namespace root logger.

Level is set to ``logging.WARNING=30`` by default (or ``DEBUG`` if ``ENABLE_VERBOSE_LOGGING`` is set).
See :doc:`/documentation/translation-logging` for details.
"""
if LOGGER.level == _l.NOTSET:
    LOGGER.setLevel(_l.DEBUG if ENABLE_VERBOSE_LOGGING else _l.WARNING)


def enable_verbose_debug_messages(
    level: _t.Literal["verbose", "debug", "info", "warning"] = "verbose",
    *,
    use_custom_handler: bool | _t.Literal["auto"] = "auto",
    style: _t.Literal["minimal", "basic", "pretty", "rainbow"] = "pretty",
) -> _t.ContextManager[None]:
    """Enable verbose logging. May be used as a context.

    .. hint::

       Click `here <../_static/logging-style-rainbow.html>`__ for verbose sample output using ``style="rainbow"``.

    **Styles**

    * **minimal**: Nothing but the logged message itself.
    * **basic**: Adds logger name and level.
    * **pretty**: Adds basic color and task ID (e.g. ``🍏 0x2b92``). Mark stage (``enter=🚀, exit=✅``).
    * **rainbow**: Indent based on stage. Full-color syntax highlighting for strings and keywords.

    Args:
        level: Log level. If `'verbose'` (default), set :attr:`ENABLE_VERBOSE_LOGGING` to ``True``.
        use_custom_handler: Set to ``False`` to use existing handlers. If `'auto'` (default), use existing handlers if
            one is found (see :py:meth:`logging.Logger.hasHandlers`). If ``True``, propagation is disabled for the
            :data:`namespace root logger <LOGGER>`.
        style: Formatting style to use. Ignored when `use_custom_handler` evaluates to ``False``.

    Examples:
        Basic usage.

        >>> from id_translation.mapping import Mapper
        >>> with enable_verbose_debug_messages():
        ...     # Context manager; changes are temporary.
        ...     Mapper().apply("ab", candidates="abc")

        Forcing custom handlers. These add formatting (e.g. color) to namespace logger messages.

        >>> enable_verbose_debug_messages(use_custom_handler=True, style="rainbow")
        >>> Mapper().apply("ab", candidates="abc")

        The changes aren't automatically undone if a regular function call is used.

    Notes:
        Custom handlers emit to standard out.
    """
    global ENABLE_VERBOSE_LOGGING  # noqa: PLW0603

    if level.lower() == "verbose":
        level = "debug"
        verbose = True
    else:
        verbose = False

    verbose_before = ENABLE_VERBOSE_LOGGING
    level_before = LOGGER.level
    propagate_before = LOGGER.propagate

    LOGGER.setLevel(_l._nameToLevel[level.upper()])
    ENABLE_VERBOSE_LOGGING = verbose

    if use_custom_handler == "auto" and not LOGGER.hasHandlers():
        use_custom_handler = True

    handler: _l.Handler | None = None
    if use_custom_handler is True:
        from sys import stdout  # noqa: PLC0415

        if style == "minimal":
            formatter = _l.Formatter("%(message)s")
        elif style == "basic":
            formatter = _l.Formatter("[%(name)s:%(levelname)s] %(message)s")
        else:
            from ._utils.debug_logging_formatter import DebugLoggingFormatter  # noqa: PLC0415

            formatter = DebugLoggingFormatter(less=style == "pretty", indent_style=".." if verbose else "")

        handler = _l.StreamHandler(stdout)
        handler.setFormatter(formatter)
        LOGGER.addHandler(handler)
        LOGGER.propagate = False  # Prevent duplicate output.

    def undo() -> None:
        """Restore original state."""
        global ENABLE_VERBOSE_LOGGING  # noqa: PLW0603

        LOGGER.setLevel(level_before)
        ENABLE_VERBOSE_LOGGING = verbose_before

        if handler:
            LOGGER.propagate = propagate_before
            LOGGER.removeHandler(handler)

    class Undo(_t.ContextManager[None]):
        def __exit__(self, *_: _t.Any) -> None:
            undo()

    return Undo()


def generate_task_id(seed: float | None = None) -> int:
    """Generate a new task ID."""
    if seed is None:
        seed = _perf_counter()
    random = _Random(seed)  # noqa: S311
    return random.randint(0, 65535)  # 65535 = 0xFFFF


def get_event_key(method: _t.Any, stage: str) -> str:
    """Construct `event_key` value."""
    cls = type(method.__self__).__name__
    return f"{cls}.{method.__name__}:{stage}"
