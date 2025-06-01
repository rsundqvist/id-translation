"""Types used for mapping."""

import typing as _t
from collections import abc as _abc

if _t.TYPE_CHECKING:
    from ._cardinality import Cardinality

HL = _t.TypeVar("HL", bound=_abc.Hashable)
"""Hashable type on the left side of a directional relationship."""
HR = _t.TypeVar("HR", bound=_abc.Hashable)
"""Hashable type on the right side of a directional relationship."""
LeftToRight = dict[HL, tuple[HR, ...]]
"""A left-to-right mapping."""
RightToLeft = dict[HR, tuple[HL, ...]]
"""A right-to-left mapping."""

ValueType = _t.TypeVar("ValueType", bound=_abc.Hashable)
"""A type of item being mapped."""
CandidateType = _t.TypeVar("CandidateType", bound=_abc.Hashable)
"""A type of item being mapped."""
MatchTuple = tuple[CandidateType, ...]
"""A tuple of candidates matched to a value."""
ContextType = _t.TypeVar("ContextType", bound=_abc.Hashable)
"""Type of context in which mapping is being performed."""

CardinalityType = _t.Union[str, "Cardinality"]

UserOverrideFunction = _abc.Callable[
    [ValueType, set[CandidateType], ContextType | None],
    CandidateType | None,
]
"""Signature for a user-defined override function.

Args:
    value: An element to find matches for.
    candidates: Potential matches for `value`.
    context: The context in which scoring is being performed.

Returns:
    Either ``None`` (let regular logic decide) or a single candidate `c` in `candidates`.
"""

ScoreFunction = _abc.Callable[
    [ValueType, _abc.Iterable[CandidateType], ContextType | None],
    _abc.Iterable[float],
]
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

AliasFunction = _abc.Callable[
    [ValueType, _abc.Iterable[CandidateType], ContextType | None],
    tuple[ValueType, _abc.Iterable[CandidateType]],
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

FilterFunction = _abc.Callable[
    [ValueType, _abc.Iterable[CandidateType], ContextType | None],
    set[CandidateType],
]
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

HeuristicsTypes: _t.TypeAlias = (
    AliasFunction[ValueType, CandidateType, ContextType] | FilterFunction[ValueType, CandidateType, ContextType]
)
"""Types that may be interpreted as a score function heuristic."""

OnUnmapped = _t.Literal["raise", "warn", "ignore"]
"""Action types for unmapped values."""
OnUnknownUserOverride = _t.Literal["raise", "warn", "keep"]
"""Action types for bad user overrides (dict or function)."""
