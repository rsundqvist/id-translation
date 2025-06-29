"""Functions and classes used by the :class:`.Mapper` for handling score matrices.

.. warning::

   This module is considered an implementation detail, and may change without notice.
"""

import warnings
from contextlib import contextmanager as _contextmanager

warnings.warn(
    "This module is considered an implementation detail, and may change without notice.", UserWarning, stacklevel=2
)


@_contextmanager
def enable_verbose_debug_messages():  # type: ignore  # noqa
    """Temporarily enable verbose DEBUG-level logger messages.

    Returns a context manager. Calling the function without the ``with`` statement does nothing.

    >>> from id_translation.mapping import Mapper, support
    >>> with support.enable_verbose_debug_messages():
    ...     Mapper().apply("ab", candidates="abc")
    """
    from . import _VERBOSE_LOGGER, _mapper, filter_functions, heuristic_functions, score_functions

    before = filter_functions.VERBOSE, heuristic_functions.VERBOSE, score_functions.VERBOSE, _VERBOSE_LOGGER.disabled
    enable = (True, True, True, False)

    if before == enable:
        yield
        return

    try:
        (
            filter_functions.VERBOSE,
            heuristic_functions.VERBOSE,
            score_functions.VERBOSE,
            _VERBOSE_LOGGER.disabled,
        ) = enable
        _mapper.FORCE_VERBOSE = True
        yield
    finally:
        (
            filter_functions.VERBOSE,
            heuristic_functions.VERBOSE,
            score_functions.VERBOSE,
            _VERBOSE_LOGGER.disabled,
        ) = before
        _mapper.FORCE_VERBOSE = False
