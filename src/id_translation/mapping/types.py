"""Types used for mapping."""
import typing as _t

HL = _t.TypeVar("HL", bound=_t.Hashable)
"""_t.Hashable type on the left side of a directional relationship."""
HR = _t.TypeVar("HR", bound=_t.Hashable)
"""_t.Hashable type on the right side of a directional relationship."""
LeftToRight = _t.Dict[HL, _t.Tuple[HR, ...]]
"""A left-to-right mapping."""
RightToLeft = _t.Dict[HR, _t.Tuple[HL, ...]]
"""A right-to-left mapping."""

ValueType = _t.TypeVar("ValueType", bound=_t.Hashable)
"""A type of item being mapped."""
CandidateType = _t.TypeVar("CandidateType", bound=_t.Hashable)
"""A type of item being mapped."""
MatchTuple = _t.Tuple[CandidateType, ...]
"""A tuple of candidates matched to a value."""
ContextType = _t.TypeVar("ContextType", bound=_t.Hashable)
"""Type of context in which mapping is being performed."""

UserOverrideFunction = _t.Callable[
    [ValueType, _t.Set[CandidateType], _t.Optional[ContextType]],
    _t.Optional[CandidateType],
]
"""Signature for a user-defined override function.

Args:
    value: An element to find matches for.
    candidates: Potential matches for `value`.
    context: The context in which scoring is being performed.

Returns:
    Either ``None`` (let regular logic decide) or a single candidate `c` in `candidates`.
"""

ScoreFunction = _t.Callable[
    [ValueType, _t.Iterable[CandidateType], _t.Optional[ContextType]],
    _t.Iterable[float],
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

AliasFunction = _t.Callable[
    [ValueType, _t.Iterable[CandidateType], _t.Optional[ContextType]],
    _t.Tuple[ValueType, _t.Iterable[CandidateType]],
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

FilterFunction = _t.Callable[
    [ValueType, _t.Iterable[CandidateType], _t.Optional[ContextType]],
    _t.Set[CandidateType],
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

HeuristicsTypes = _t.Union[
    AliasFunction[ValueType, CandidateType, ContextType],
    FilterFunction[ValueType, CandidateType, ContextType],
]
"""Types that may be interpreted as a score function heuristic."""
