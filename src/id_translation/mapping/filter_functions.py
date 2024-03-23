"""Functions that return a subset of candidates with which to continue the matching procedure."""

import logging
import re
from collections.abc import Iterable as _Iterable
from typing import Any as _Any

from ..types import ID
from . import exceptions

VERBOSE: bool = False
LOGGER = logging.getLogger(__package__).getChild("verbose").getChild("filter_functions")


def filter_names(
    value: str,
    candidates: _Iterable[str],
    context: _Any,
    regex: str,
    remove: bool = False,
) -> set[str]:
    """Filter names to translate based on `regex`.

    Analogous to the built-in :py:func:`filter`-function, ``filter_names`` keep only the names that match the given
    `regex`. This behavior may be reversed by setting the `remove` flag to ``True``.

    Args:
        value: A name that should be mapped one of the sources in `candidates`.
        candidates: Candidate sources.
        context: Should be ``None``. Always ignored, exists for compatibility.
        regex: A regex pattern. Will be matched against the `value`.
        remove: If ``True``, remove matching values.

    Returns:
        The original candidates if `value` matches the given `regex`. An empty set, otherwise.

    Examples:
        Ensuring that untranslatable IDs are left as-is.

        >>> candidates, context = {"id", "name", "birth_date"}, None
        >>> value = "employee_id"
        >>> allowed = filter_names(
        ...     value,
        ...     candidates,
        ...     context,
        ...     regex=".*_id$",
        ...     remove=False,  # This is the default (like the built-in filter).
        ... )
        >>> sorted(allowed)
        ['birth_date', 'id', 'name']

        The expression used selects names that end with `'_id'`.
    """
    function_name = filter_names.__name__
    _check_context(function_name, context=context, want_none=True)
    keep = _filter_single(
        value,
        regex=regex,
        remove=remove,
        label="name",
        function_name=function_name,
        action="Do not translate",
    )
    return set(candidates) if keep else set()


def filter_sources(
    value: str,
    candidates: _Iterable[str],
    context: _Any,
    regex: str,
    remove: bool = False,
) -> set[str]:
    """Filter sources based on `regex`.

    Args:
        value: Target placeholder. Return immediately if `value` != `'id'` to avoid unnecessary work.
        candidates: Available placeholders in the source named by `context`. Always ignored, exists for compatibility.
        context: The source to which the `candidates` belong.
        regex: A regex pattern. Will be matched against the `context`.
        remove: If ``True``, remove matching values.

    Returns:
        The original candidates if `context` does NOT match the given `regex`. An empty set, otherwise.

    Examples:
        Avoiding uninteresting sources (for ID translation purposes).

        >>> value, candidates = "id", {"ignored"}
        >>> context = "some_metadata_table"
        >>> allowed = filter_sources(
        ...     "id",
        ...     candidates,
        ...     context,
        ...     regex=".*metadata.*",
        ...     remove=True,
        ... )
        >>> len(allowed) == 0
        True

        The expression used filters out sources that contain the word `'metadata'`.
    """
    if value != ID:
        return set(candidates)

    function_name = filter_names.__name__
    _check_context(function_name, context=context, want_none=False)
    keep = _filter_single(
        context,
        regex=regex,
        remove=remove,
        label="source",
        function_name=function_name,
    )
    return set(candidates) if keep else set()


def filter_placeholders(
    value: str,  # noqa: ARG001
    candidates: _Iterable[str],
    context: _Any,
    regex: str,
    remove: bool = False,
) -> set[str]:
    """Filter placeholders, as they appear in the source given by `context`, based on `regex`.

    Args:
        value: Target placeholder. Always ignored, exists for compatibility.
        candidates: Available placeholders in the source named by `context`.
        context: The source to which the `candidates` belong.
        regex: A regex pattern. Will be matched against elements of the `candidates`.
        remove: If ``True``, remove matching values.

    Returns:
        Placeholders that may be used.

    Examples:
        Removing irrelevant but possibly confusing columns.

        >>> value, context = "ignored", "ignored"
        >>> candidates = {"id", "name", "old_id", "previous_id"}
        >>> allowed = filter_placeholders(
        ...     value,
        ...     candidates,
        ...     context,
        ...     regex="^(old|previous).*",
        ...     remove=True,
        ... )
        >>> sorted(allowed)
        ['id', 'name']
    """
    _check_context(filter_placeholders.__name__, context=context, want_none=False)

    pattern = re.compile(regex, flags=re.IGNORECASE)
    candidates = set(candidates)
    ans = {c for c in candidates if (pattern.match(c) is None) is remove}

    if VERBOSE:
        logger = LOGGER.getChild(filter_placeholders.__name__)
        if logger.isEnabledFor(logging.DEBUG) and len(ans) < len(candidates):
            removed = candidates.difference(ans)
            logger.debug(f"Discard placeholders={removed!r} in source={context!r}; matches {pattern=}.")

    return ans


def _check_context(name: str, context: _Any, want_none: bool) -> None:
    if (context is None) is want_none:
        return

    purpose = "name-to-source" if want_none else "placeholder"
    raise exceptions.BadFilterError(f"Function '{__name__}.{name}' should only be used for {purpose} mapping.")


def _filter_single(
    string: str,
    regex: str,
    remove: bool,
    label: str,
    function_name: str,
    action: str = "Discard",
) -> bool:
    keep = (re.match(regex, string, re.IGNORECASE) is None) is remove

    if not keep and VERBOSE:
        logger = LOGGER.getChild(function_name)
        if logger.isEnabledFor(logging.DEBUG):
            pattern = re.compile(regex, re.IGNORECASE)
            logger.debug(f"%s %s={string!r}; %s {pattern=}.", action, label, "matches" if remove else "does not match")

    return keep
