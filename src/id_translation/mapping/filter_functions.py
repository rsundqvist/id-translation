"""Functions that remove candidates."""
from __future__ import annotations

import logging
import re
from typing import Collection, Iterable, List, Literal, Optional, Set, Tuple, Union

LOGGER = logging.getLogger(__name__)

WhereOptions = Literal["name", "context", "candidate"]
WHERE_OPTIONS = ("name", "candidate", "context")
WhereArg = Union[WhereOptions, Iterable[WhereOptions]]
"""Determines how where matches must be found during filtering operations."""

VERBOSE: bool = False
"""If ``True`` enable optional DEBUG-level log messages on each heuristic function invocation.

Notes:
    Not all functions have verbose messages.
"""


def require_regex_match(
    name: str,
    candidates: Iterable[str],
    context: Optional[str],
    regex: Union[str, re.Pattern[str]],
    where: WhereArg,
    keep_if_match: bool = True,
    purpose: str = "matching",
) -> Set[str]:
    """Require a regex match in `name`, `context`, and/or `candidates`.

    Args:
        name: A name.
        candidates: Potential matches for `name`.
        context: Context in which the function is being called.
        regex: A regex pattern to pass to :py:func:`re.compile`.
        where: Which of ('name', 'candidate', 'context') to match in.
        keep_if_match: If ``False``, require that `regex` does _not_ match to keep candidates.
        purpose: A purpose-string used for logging.

    Returns:
        Approved candidates.

    Raises:
        ValueError: If `where` contains `'context'` when `context` is not given.

    See Also:
        The :meth:`banned_substring` method.
    """
    where = _parse_where_args(where)

    pattern = re.compile(regex, flags=re.IGNORECASE) if isinstance(regex, str) else regex
    logger = LOGGER.getChild("require_regex_match")
    candidates = set(candidates)

    # Short-circuit full refusal
    if "name" in where:
        match = pattern.match(name)
        if keep_if_match and not match:
            if VERBOSE:
                logger.debug(f"Refuse {purpose} for {name=}: Does not match {pattern=}.")
            return set()
        if match and not keep_if_match:
            if VERBOSE:
                logger.debug(f"Refuse {purpose} for {name=}: Matches {pattern=}.")
            return set()

    if "context" in where:
        if context is None:
            raise ValueError(f"No context given but 'context' was found in {where=}.")  # pragma: no cover

        match = pattern.match(context)
        if keep_if_match and not match:
            if VERBOSE:
                logger.debug(f"Refuse {purpose} for {context=}: Does not match {pattern=}.")
            return set()
        if match and not keep_if_match:
            if VERBOSE:
                logger.debug(f"Refuse {purpose} for {context=}: Matches {pattern=}.")
            return set()

    if "candidate" not in where:
        return candidates

    kept: List[str] = []
    rejected: List[str] = []
    for cand in candidates:
        lst = kept if (bool(pattern.match(cand)) is keep_if_match) else rejected
        lst.append(cand)

    if VERBOSE and logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"Filtering with {keep_if_match=} and {pattern=}; kept {sorted(kept)}, rejected {rejected}.")

    return set(kept)


def banned_substring(
    name: str,
    candidates: Iterable[str],
    context: Optional[str],
    substrings: Collection[str],
    where: WhereArg,
) -> Set[str]:
    """Prevent mapping if banned substrings are found.

    Matching on `name` or `context` halts all mapping. Matching candidates excludes only those candidates.

    Args:
        name: An element to find matches for.
        candidates: Potential matches for `name` (not used).
        context: Context in which the function is being called.
        substrings: Substrings which may not be present in `name`.
        where: Which of ('name', 'candidate', 'context') to match in. Empty=all.

    Returns:
        Approved candidates.

    See Also:
        The :meth:`require_regex_match` method, which performs the actual work.
    """
    where = _parse_where_args(where)

    remaining = set(candidates)

    for subs in substrings:
        if not remaining:
            break

        matches = require_regex_match(
            name,
            remaining,
            context,
            regex=re.compile(f".*{subs}.*", flags=re.IGNORECASE),
            where=where,
            keep_if_match=False,
        )
        remaining = remaining.intersection(matches)

    return remaining


def _parse_where_args(args: WhereArg) -> Tuple[WhereOptions, ...]:
    if not args:
        raise ValueError(f"At least one of {WHERE_OPTIONS} must be given.")

    args_tuple = tuple((args,) if isinstance(args, str) else tuple(args))
    for where in args_tuple:
        if where not in WHERE_OPTIONS:
            raise ValueError(f"Bad where-argument {repr(args)}; {where=} not in {WHERE_OPTIONS}.")
    return args_tuple
