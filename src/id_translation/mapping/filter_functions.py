"""Functions that return a subset of candidates with which to continue the matching procedure."""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Set

from id_translation.mapping import exceptions
from id_translation.types import ID

VERBOSE: bool = False
LOGGER = logging.getLogger(__package__).getChild("verbose").getChild("filter_functions")


def keep_names(
    value: str,
    candidates: Iterable[str],
    context: Any,
    regex: str,
) -> Set[str]:
    """Only translate names that match a regex.

    Args:
        value: A name that should be mapped one of the sources in `candidates`.
        candidates: Candidate sources.
        context: Should be ``None``. Always ignored, exists for compatibility.
        regex: A regex pattern. Will be matched against the `value`.

    Returns:
        The original candidates if `value` matches the given `regex`. An empty set, otherwise.

    Examples:
        Ensuring that untranslatable IDs are left as-is.

        >>> candidates, context = ["id", "name", "birth_date"], None
        >>> value = "employee_id"
        >>> allowed = keep_names(
        ...     value, candidates, context,
        ...     regex=".*_id$"
        ... )
        >>> sorted(allowed)
        ['birth_date', 'id', 'name']

        The expression used selects names that end with `'_id'`.
    """
    _check_context(context, name=keep_names.__name__, want_none=True)

    pattern = re.compile(regex, re.IGNORECASE)
    keep = pattern.match(value) is not None

    if not keep and VERBOSE:
        logger = LOGGER.getChild(keep_names.__name__)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Discard name={value!r}; does not match {pattern=}.")

    return set(candidates) if keep else set()


def remove_names(
    value: str,
    candidates: Iterable[str],
    context: Any,
    regex: str,
) -> Set[str]:
    """Ignore names that match a regex.

    Args:
        value: A name that should be mapped one of the sources in `candidates`.
        candidates: Candidate sources.
        context: Should be ``None``. Always ignored, exists for compatibility.
        regex: A regex pattern. Will be matched against the `value`.

    Returns:
        An empty set if `value` matches the given `regex`. The original candidates, otherwise.

    Examples:
        Ensuring that untranslatable IDs are left as-is.

        >>> candidates, context = ["ignored"], None
        >>> value = "card_id"
        >>> allowed = remove_names(
        ...     value, candidates, context,
        ...     regex="^.*(card|session)_id$"
        ... )
        >>> len(allowed) == 0
        True

        The expression used filters out names that end in either `'card_id'` or `'session_id'`.
    """
    _check_context(context, name=remove_names.__name__, want_none=True)

    pattern = re.compile(regex, re.IGNORECASE)
    keep = pattern.match(value) is None

    if not keep and VERBOSE:
        logger = LOGGER.getChild(remove_names.__name__)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Discard name={value!r}; matches {pattern=}.")

    return set(candidates) if keep else set()


def remove_sources(
    value: str,
    candidates: Iterable[str],
    context: Any,
    regex: str,
) -> Set[str]:
    """Disallow fetching from matching sources.

    Args:
        value: Target placeholder. Return immediately if `value` != `'id'` to avoid unnecessary work.
        candidates: Available placeholders in the source named by `context`. Always ignored, exists for compatibility.
        context: The source to which the `candidates` belong.
        regex: A regex pattern. Will be matched against the `context`.

    Returns:
        The original candidates if `context` does NOT match the given `regex`. An empty set, otherwise.

    Examples:
        Avoiding uninteresting sources (for ID translation purposes).

        >>> value, candidates = "id", ["ignored"]
        >>> context = "some_metadata_table"
        >>> allowed = remove_sources(
        ...     "id", candidates, context,
        ...     regex=".*metadata.*"
        ... )
        >>> len(allowed) == 0
        True

        The expression used filters out sources that contain the word `'metadata'`.
    """
    if value != ID:
        return set(candidates)

    _check_context(context, name=remove_sources.__name__, want_none=False)

    pattern = re.compile(regex, re.IGNORECASE)
    keep = pattern.match(context) is None

    if VERBOSE:
        logger = LOGGER.getChild(remove_sources.__name__)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Discard source={context!r}; matches {pattern=}.")

    return set(candidates) if keep else set()


def remove_placeholders(
    value: str,
    candidates: Iterable[str],
    context: Any,
    regex: str,
) -> Set[str]:
    """Disallow fetching of matching placeholders.

    Args:
        value: Target placeholder. Always ignored, exists for compatibility.
        candidates: Available placeholders in the source named by `context`.
        context: The source to which the `candidates` belong.
        regex: A regex pattern. Will be matched against elements of the `candidtes`.

    Returns:
        Placeholders that may be used.

    Examples:
        Removing irrelevant but possibly confusing columns.

        >>> value, context = "ignored", "ignored"
        >>> candidates = ["id", "name", "old_id", "previous_id"]
        >>> allowed = remove_placeholders(
        ...     value, candidates, context,
        ...     regex="^(old|previous).*"
        ... )
        >>> sorted(allowed)
        ['id', 'name']
    """
    _check_context(context, name=remove_placeholders.__name__, want_none=False)

    pattern = re.compile(regex, flags=re.IGNORECASE)
    candidates = set(candidates)
    ans = {c for c in candidates if not pattern.match(c)}

    if VERBOSE:
        logger = LOGGER.getChild(remove_placeholders.__name__)
        if logger.isEnabledFor(logging.DEBUG):
            if len(ans) < len(candidates):
                removed = candidates.difference(ans)
                logger.debug(f"Discard placeholders={removed!r} in source={context!r}; matches {pattern=}.")

    return ans


def _check_context(context: Any, name: str, want_none: bool) -> None:
    if (context is None) is want_none:
        return

    raise exceptions.BadFilterError(
        f"Function {__name__}.{name!r} should only be used for {'name-to-source' if want_none else 'placeholder'} "
        f"mapping. Bad [[<'translation' or 'fetching'>.mapping.filter_functions]]-section in the TOML configuration?"
    )
