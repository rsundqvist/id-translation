"""Logging utilities; see :doc:`/documentation/translation-logging` for help."""

import logging as _l
import typing as _t
from collections.abc import Generator as _Generator
from contextlib import contextmanager as _contextmanager
from random import Random as _Random
from time import perf_counter as _perf_counter

from rics.env import read as _env

ENABLE_VERBOSE_LOGGING: bool = _env.read_bool("ID_TRANSLATION_VERBOSE")
"""Set to enable additional ``DEBUG``-level messages.

The default (``False``) is controlled by the :envvar:`ID_TRANSLATION_VERBOSE` variable. Use
:func:`enable_verbose_debug_messages` to enable temporarily.
"""

LOGGER = _l.getLogger("id_translation")
"""Root logger instance.

Level is set to ``logging.WARNING=30`` by default (or ``DEBUG`` if ``ENABLE_VERBOSE_LOGGING`` is set).
See :doc:`/documentation/translation-logging` for details.
"""
if LOGGER.level == _l.NOTSET:
    LOGGER.setLevel(_l.DEBUG if ENABLE_VERBOSE_LOGGING else _l.WARNING)


@_contextmanager
def enable_verbose_debug_messages() -> _Generator[None]:
    """Verbose logging context.

    Temporarily set ``ENABLE_VERBOSE_LOGGING=True`` and ``logger.getLogger('id_translation')`` level to ``DEBUG``.

    >>> from id_translation.mapping import Mapper
    >>> from id_translation.logging import enable_verbose_debug_messages
    >>> with enable_verbose_debug_messages():
    ...     Mapper().apply("ab", candidates="abc")
    """
    global ENABLE_VERBOSE_LOGGING  # noqa: PLW0603

    level_before = LOGGER.level
    LOGGER.setLevel(_l.DEBUG)

    verbose_before = ENABLE_VERBOSE_LOGGING
    ENABLE_VERBOSE_LOGGING = True

    try:
        yield
    finally:
        LOGGER.setLevel(level_before)
        ENABLE_VERBOSE_LOGGING = verbose_before


def generate_task_id(seed: float | None = None) -> int:
    """Generate a new task ID."""
    if seed is None:
        seed = _perf_counter()
    random = _Random(seed)  # noqa: S311
    return random.randint(0, 65535)


def get_event_key(method: _t.Any, stage: str) -> str:
    """Construct `event_key` value."""
    cls = type(method.__self__).__name__
    return f"{cls}.{method.__name__}:{stage}"
