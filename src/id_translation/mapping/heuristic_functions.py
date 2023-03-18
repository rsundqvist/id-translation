"""Functions which perform heuristics for score functions.

See Also:
    The :class:`~.HeuristicScore` class.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional, Set, Tuple, Union

from . import filter_functions as ff
from .types import ContextType

VERBOSE: bool = False
"""If ``True`` enable optional DEBUG-level log messages on each heuristic function invocation.

Notes:
    Not all functions have verbose messages.
"""


def like_database_table(
    name: str,
    candidates: Iterable[str],
    context: Optional[ContextType],
) -> Tuple[str, List[str]]:
    """Try to make `value` look like the name of a database table."""

    def apply(s: str) -> str:
        s = s.lower().replace("_", "").replace(".", "")
        s = s[: -len("id")] if s.endswith("id") else s
        s = s if s.endswith("s") else s + "s"
        return s

    return apply(name), list(map(apply, candidates))


def short_circuit_to_value(
    value: str,
    candidates: Iterable[str],
    context: Optional[str],
    regex: Union[str, re.Pattern[str]],
    target: str,
) -> Set[str]:
    """Short circuit candidates which match a given `regex` a given to-value.

    Args:
        value: A value to map.
        candidates: Candidates for `value`.
        context: Context in which the function is being called.
        regex: A pattern in `candidates` which should trigger forced short-circuit matching.
        target: The target value. If ``value != target``, an empty set is always returned.

    Returns:
        Candidates which match `regex`, or an empty set.

    Notes:
        This is technically a filter function and may be used as such.
    """
    return (
        set()
        if value != target
        else ff.require_regex_match(
            value,
            candidates,
            context,
            regex=regex,
            where="candidate",
            purpose=f"short-circuiting to value-{target=}",
        )
    )


def short_circuit_to_candidate(
    value: str,
    candidates: Iterable[str],
    context: Optional[str],
    regex: Union[str, re.Pattern[str]],
    target: str,
) -> Set[str]:
    """Short circuit candidates which match a given `regex` to a given to-candidate.

    Args:
        value: A value to map.
        candidates: Candidates for `value`.
        context: Context in which the function is being called.
        regex: A pattern in `candidates` which should trigger forced short-circuit matching.
        target: A target candidate. Must be present in `candidates`, or empty set is always returned.

    Returns:
        Candidates which match `regex`, or an empty set.

    Notes:
        This is technically a filter function and may be used as such.
    """
    return (
        set()
        if target not in candidates
        else ff.require_regex_match(
            value,
            [target],
            context,
            regex=regex,
            where="name",
            purpose=f"short-circuiting to candidate-{target=}",
        )
    )


def force_lower_case(
    value: str, candidates: Iterable[str], context: Optional[ContextType]
) -> Tuple[str, Iterable[str]]:
    """Force lower-case in `value` and `candidates`."""
    return value.lower(), list(map(str.lower, candidates))


def value_fstring_alias(
    value: str,
    candidates: Iterable[str],
    context: Optional[ContextType],
    fstring: str,
    for_value: str = None,
    **kwargs: Any,
) -> Tuple[str, Iterable[str]]:
    """Return a value formatted by `fstring`.

    Args:
        value: An element to find matches for.
        candidates: Potential matches for `value`. Not used (returned as given).
        context: Context in which the function is being called.
        fstring: The format string to use. Can use `value` and `context` as placeholders.
        for_value: If given, apply only if ``value == for_value``. When `if_value_equals` is given, `fstring` arguments
            which do not use the `value` as a placeholder key are permitted.
        **kwargs: Additional keyword placeholders in `fstring`.

    Returns:
        A tuple ``(formatted_value, candidates)``.

    Raises:
        ValueError: If `fstring` does not contain a placeholder `'value'` and `for_value` is not given.
    """
    if not for_value and "{value}" not in fstring:
        # No longer a function of the value.
        raise ValueError(
            f"Invalid {fstring=} passed to value_fstring_alias(); does not contain {{value}}. "
            "To allow, the 'for_value' parameter must be given as well."
        )

    if for_value and value != for_value:
        return value, candidates

    return fstring.format(value=value, context=context, **kwargs), candidates


def candidate_fstring_alias(
    value: str,
    candidates: Iterable[str],
    context: Optional[ContextType],
    fstring: str,
    **kwargs: Any,
) -> Tuple[str, Iterable[str]]:
    """Return candidates formatted by `fstring`.

    Args:
        value: An element to find matches for. Not used (returned as given).
        candidates: Potential matches for `value`.
        context: Context in which the function is being called.
        fstring: The format string to use. Can use `value`, `context`, and elements of `candidates` as placeholders.
        **kwargs: Additional keyword placeholders in `fstring`.

    Returns:
        A tuple ``(value, formatted_candidates)``.

    Raises:
        ValueError: If `fstring` does not contain a placeholder `'candidate'`.
    """
    if "{candidate}" not in fstring:
        raise ValueError(f"Invalid {fstring=} passed to candidate_fstring_alias(); does not contain {{candidate}}.")

    return value, map(lambda c: fstring.format(value=value, candidate=c, context=context, **kwargs), candidates)
