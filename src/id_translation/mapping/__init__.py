"""Mapping implementations for matching groups of elements.

For and introduction to mapping, see :ref:`mapping-primer`.
"""

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
