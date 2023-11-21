"""Functions which perform heuristics for score functions.

See Also:
    The :class:`~.HeuristicScore` class.
"""
from __future__ import annotations

import logging
import re
from typing import Any as _Any, Iterable, List, Set, Tuple, Union

VERBOSE: bool = False
LOGGER = logging.getLogger(__package__).getChild("verbose").getChild("heuristic_functions")


def like_database_table(
    name: str,
    candidates: Iterable[str],
    context: _Any,
) -> Tuple[str, List[str]]:
    """Try to make `value` look like the name of a database table."""

    def apply(s: str) -> str:
        s = s.lower()
        if s == "id":
            return "id"
        s = s[: -len("id")] if s.endswith("id") else s
        s = s.replace("_", "").replace(".", "")

        if s[-1] == "s":
            pass  # Assume that any word ending in "s" is already pluralized.
        elif s[-1] in "xz" or (s[-1] == "h" and s[-2] in "sc"):
            s += "es"
        else:
            s += "s"

        return s

    return apply(name), list(map(apply, candidates))


def short_circuit(
    value: str,
    candidates: Set[str],
    context: _Any,
    value_regex: Union[str, re.Pattern[str]],
    target_candidate: str,
) -> Set[str]:
    """Short circuit `value` to the target candidate if the target and regex conditions are met.

    If `target_candidate` is in `candidates` and `value` matches the given `value_regex`, a single-element set
    ``{target_candidate}`` is returned which will trigger short-circuiting in the calling ``Mapper``. If either of
    these conditions fail, an empty set is returned and the mapping procedure will continue.

    Args:
        value: A value to map.
        candidates: Candidates for `value`.
        context: Always ignored, exists for compatibility.
        value_regex: A pattern match against `value`. Case-insensitive by default.
        target_candidate: The candidate to short circuit to.

    Returns:
        A single-element set ``{target_candidate}``, iff both conditions are met. An empty set otherwise.


    Examples:
        The main purpose of this method is to bind any name (a `value`) matching the given regex pattern to a
        pre-defined source (a `candidate`, e.g. a table in a SQL database). For example, to always match any bite
        victim-columns to the `humans` table (see the :ref:`translation-primer` page), we might specify:

        >>> value = "first_bite_victim"
        >>> value_regex= ".*_bite_victim$"  # If the column ends with '_bite_victim'..
        >>> target_candidate = "humans"  # Match it to the 'humans' table.
        >>> short_circuit(value, {"humans", "animals"}, None, value_regex, target_candidate)
        {'humans'}

        Short-circuiting will only trigger of both conditions are met. If the example below, we can see that no value is
        returned since the target candidate is not among the given candidates.

        >>> short_circuit(value, {"animals"}, None, value_regex, target_candidate)
        set()
    """
    candidates = set(candidates)
    pattern = re.compile(value_regex, flags=re.IGNORECASE) if isinstance(value_regex, str) else value_regex

    if target_candidate not in candidates:
        LOGGER.getChild("short_circuit").debug(
            f"Short-circuiting failed for {value=}: The {target_candidate=} is an input candidate."
        )
        return set()

    if not pattern.match(value):
        LOGGER.getChild("short_circuit").debug(f"Short-circuiting failed for {value=}: Does not match {pattern=}.")
        return set()

    return {target_candidate}


def force_lower_case(value: str, candidates: Iterable[str], context: _Any) -> Tuple[str, Iterable[str]]:
    """Force lower-case in `value` and `candidates`."""
    return value.lower(), list(map(str.lower, candidates))


def value_fstring_alias(
    value: str,
    candidates: Iterable[str],
    context: _Any,
    fstring: str,
    for_value: str = None,
    **kwargs: _Any,
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
    context: _Any,
    fstring: str,
    **kwargs: _Any,
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
