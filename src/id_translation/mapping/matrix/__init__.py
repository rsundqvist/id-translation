"""Functions and classes used by the :class:`.Mapper` for handling score matrices.

.. warning::

   This module is considered an implementation detail, and may change without notice.
"""

from warnings import warn as _warn

from ._score_helper import Record, Reject, ScoreHelper
from ._score_matrix import ScoreMatrix

__all__ = [
    "Record",
    "Reject",
    "ScoreHelper",
    "ScoreMatrix",
]

_warn(
    "This module is considered an implementation detail, and may change without notice.",
    UserWarning,
    stacklevel=2,
)
del _warn
