"""Functions which return a likeness score.

See Also:
    The :class:`~.HeuristicScore` class.
"""

from collections.abc import Iterable as _Iterable

from . import exceptions
from .types import CandidateType, ContextType, ValueType

VERBOSE: bool = False


def modified_hamming(
    name: str,
    candidates: _Iterable[str],
    context: ContextType | None,  # noqa: ARG001
    *,
    add_length_ratio_term: bool = True,
    positional_penalty: float = 0.001,
) -> _Iterable[float]:
    """Compute hamming distance modified by length ratio, from the back. Score range is ``[0, 1]``.

    Args:
        name: A name that should be mapped one of the sources in `candidates`.
        candidates: Candidate sources.
        context: Should be ``None``. Always ignored, exists for compatibility.
        add_length_ratio_term: If ``True``, score is divided by ``abs(len(name) - len(candidate))``.
        positional_penalty: A penalty applied to prefer earlier `candidates`, according to the formulare
            ``penalty = index(candidate) * positional_penalty)``.

    Examples:
        >>> from id_translation.mapping.score_functions import modified_hamming
        >>> list(modified_hamming("aa", ["aa", "a", "ab", "aa"], context=None))
        [1.0, 0.499, 0.498, 0.997]
        >>> list(
        ...     modified_hamming(
        ...         "aa", ["aa", "a", "ab", "aa"], context=None, positional_penalty=0
        ...     )
        ... )
        [1.0, 0.5, 0.5, 1.0]
        >>> list(modified_hamming("face", ["face", "FAce", "race", "place"], context=None))
        [1.0, 0.499, 0.748, 0.372]
    """

    def _apply(candidate: str) -> float:
        sz = min(len(candidate), len(name))
        same = sum([name[i] == candidate[i] for i in range(-sz, 0)])

        ratio = (1 / (1 + abs(len(candidate) - len(name)))) if add_length_ratio_term else 1
        normalized_hamming = same / sz

        return ratio * normalized_hamming

    yield from (s - i * positional_penalty for i, s in enumerate(map(_apply, candidates)))


def equality(
    value: ValueType,
    candidates: _Iterable[CandidateType],
    context: ContextType | None,  # noqa: ARG001
) -> _Iterable[float]:
    """Return 1.0 if ``k == c_i``, 0.0 otherwise.

    Examples:
        >>> from id_translation.mapping.score_functions import equality
        >>> list(equality("a", "aAb", context=None))
        [1.0, 0.0, 0.0]
    """
    yield from map(float, (value == c for c in candidates))


def disabled(
    value: ValueType,
    candidates: _Iterable[CandidateType],
    context: ContextType | None,
    strict: bool = True,
) -> _Iterable[float]:
    """Special value to indicate that scoring logic has been disabled.

    This is a workaround to allow users to indicate that the scoring logic is disabled, and that overrides should be
    used instead. The ``disabled``-function has no special meaning to the mapper, and will be called as any other
    scoring function.

    Returns:
        If `strict` is ``False``, negative infinity for all `candidates`, serving as a catch-all removal filter.

    Raises:
        ScoringDisabledError: If `strict` is ``True``.

    See Also:
        The :ref:`override-only-mapping` documentation.
    """
    if strict:
        raise exceptions.ScoringDisabledError(value, candidates, context)

    return [float("-inf")] * sum(1 for _ in candidates)
