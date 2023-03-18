"""Types used for mapping."""
from typing import Callable, Dict, Hashable, Iterable, Optional, Set, Tuple, TypeVar, Union

HL = TypeVar("HL", bound=Hashable)
"""Hashable type on the left side of a directional relationship."""
HR = TypeVar("HR", bound=Hashable)
"""Hashable type on the right side of a directional relationship."""
LeftToRight = Dict[HL, Tuple[HR, ...]]
"""A left-to-right mapping."""
RightToLeft = Dict[HR, Tuple[HL, ...]]
"""A right-to-left mapping."""

ValueType = TypeVar("ValueType", bound=Hashable)
"""A type of item being mapped."""
CandidateType = TypeVar("CandidateType", bound=Hashable)
"""A type of item being mapped."""
MatchTuple = Tuple[CandidateType, ...]
"""A tuple of candidates matched to a value."""
ContextType = TypeVar("ContextType", bound=Hashable)
"""Type of context in which mapping is being performed."""

UserOverrideFunction = Callable[[ValueType, Set[CandidateType], Optional[ContextType]], Optional[CandidateType]]
"""Signature for a user-defined override function.

Args:
    value: An element to find matches for.
    candidates: Potential matches for `value`.
    context: The context in which scoring is being performed.

Returns:
    Either ``None`` (let regular logic decide) or a single candidate `c` in `candidates`.
"""

ScoreFunction = Callable[[ValueType, Iterable[CandidateType], Optional[ContextType]], Iterable[float]]
"""Signature for a likeness score function.

Args:
    value: An element to find matches for.
    candidates: Potential matches for `value`.
    context: The context in which scoring is being performed.

Keyword Args:
    kwargs: Accepted only by some functions.

Yields:
    A score for each candidate `c` in `candidates`.
"""

AliasFunction = Callable[
    [ValueType, Iterable[CandidateType], Optional[ContextType]], Tuple[ValueType, Iterable[CandidateType]]
]
"""Signature for an alias function for heuristic scoring.

Args:
    value: An element to find matches for.
    candidates: Potential matches for `value`.
    context: The context in which mapping is being performed.

Keyword Args:
    kwargs: Accepted only by some functions.

Returns:
    A tuple (name, candidates) with applied heuristics to increase (or decrease) score as desired.
"""

FilterFunction = Callable[[ValueType, Iterable[CandidateType], Optional[ContextType]], Set[CandidateType]]
"""Signature for a filter function.

Args:
    value: An element to find matches for.
    candidates: Potential matches for `value`.
    context: The context in which filtering is being performed.

Keyword Args:
    kwargs: Accepted only by some functions.

Returns:
    A subset of candidates to keep.
"""

HeuristicsTypes = Union[
    AliasFunction[ValueType, CandidateType, ContextType], FilterFunction[ValueType, CandidateType, ContextType]
]
"""Types that may be interpreted as a score function heuristic."""
