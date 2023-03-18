"""Mapping implementations for matching groups of elements.

For and introduction to mapping, see :ref:`mapping-primer`.
"""
import logging as _logging

from ._cardinality import Cardinality
from ._directional_mapping import DirectionalMapping
from ._heuristic_score import HeuristicScore
from ._mapper import Mapper

__all__ = [
    "Cardinality",
    "HeuristicScore",
    "DirectionalMapping",
    "Mapper",
]

VERBOSE_LOGGER = _logging.getLogger(__package__).getChild("verbose")
"""Verbose logger. Only logs messages on the ``DEBUG`` level. Disabled by default."""
VERBOSE_LOGGER.disabled = True
