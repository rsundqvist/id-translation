"""Shared API of the :ref:`mapping processes <mapping-primer>` (e.g. names to sources)."""

from ._cardinality import Cardinality
from ._directional_mapping import DirectionalMapping
from ._heuristic_score import HeuristicScore
from ._mapper import Mapper

__all__ = [
    "Cardinality",
    "DirectionalMapping",
    "HeuristicScore",
    "Mapper",
]
