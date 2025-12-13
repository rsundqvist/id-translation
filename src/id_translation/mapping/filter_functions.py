"""Functions that return a subset of candidates with which to continue the matching procedure.

Mapping of the current `value` is aborted if an empty set is returned. Functions such as :func:`filter_names` and
:func:`filter_sources` use this to allow (or disallow) names and sources that match a given regex pattern.
"""

import logging
import re
from collections.abc import Iterable as _Iterable
from typing import Any as _Any

from .. import logging as _logging
from ..types import ID
from . import exceptions


def filter_names(
    value: str,
    candidates: _Iterable[str],
    context: _Any,
    regex: str,
    remove: bool = False,
    *,
    task_id: int | None = None,
) -> set[str]:
    """Filter names to translate based on `regex`.

    Analogous to the built-in :py:func:`filter`-function, ``filter_names`` keeps only the names (`value`) that match the
    given `regex`. This behavior may be reversed by setting the `remove` flag to ``True``.

    Args:
        value: A name that should be mapped one of the sources in `candidates`.
        candidates: Candidate sources.
        context: Should be ``None``. Always ignored, exists for compatibility.
        regex: A regex pattern. Will be matched against the `value`.
        remove: If ``True``, remove matching values.
        task_id: Used for logging.

    Returns:
        The original candidates if `value` matches the given `regex`. An empty set, otherwise.

    Examples:
        Ensuring that untranslatable IDs are left as-is.

        >>> sources = {"employees", "countries", "orders"}
        >>> name = "employee_id"
        >>> allowed = filter_names(
        ...     name,
        ...     candidates=sources,
        ...     context=None,
        ...     regex=".*_id$",
        ... )
        >>> sorted(allowed)
        ['countries', 'employees', 'orders']

        The call above kept the `'employee_id'` name (by returning all candidate sources).
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
        task_id=task_id,
    )
    return set(candidates) if keep else set()


def filter_sources(
    value: str,
    candidates: _Iterable[str],
    context: _Any,
    regex: str,
    remove: bool = False,
    *,
    task_id: int | None = None,
) -> set[str]:
    """Filter sources based on `regex`.

    Analogous to the built-in :py:func:`filter`-function, ``filter_sources`` keeps only the sources (`context`) that
    match the given `regex`. This behavior may be reversed by setting the `remove` flag to ``True``.

    Args:
        value: Target placeholder.
        candidates: Available placeholders in the source named by `context`. Always ignored, exists for compatibility.
        context: The source to which the `candidates` belong.
        regex: A regex pattern. Will be matched against the `context`.
        remove: If ``True``, remove matching values.
        task_id: Used for logging.

    Returns:
        The original candidates if `context` matches the given `regex`. An empty set, otherwise.

    Examples:
        Avoiding uninteresting sources (for ID translation purposes).

        >>> source = "some_metadata_table"
        >>> allowed = filter_sources(
        ...     "id",
        ...     candidates={"id", "name", "some_other_column"},
        ...     context=source,
        ...     regex=".*metadata.*",
        ...     remove=True,
        ... )
        >>> len(allowed)
        0

        The call above filtered out the `'some_metadata_table'` source (by removing all candidates).

    Notes:
        Returns immediately if `value` != `'id'`, to avoid unnecessary work. The
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
        task_id=task_id,
    )
    return set(candidates) if keep else set()


def filter_placeholders(
    value: str,  # noqa: ARG001
    candidates: _Iterable[str],
    context: _Any,
    regex: str,
    remove: bool = False,
    task_id: int | None = None,
) -> set[str]:
    """Filter placeholders, as they appear in the source given by `context`, based on `regex`.

    Args:
        value: Target placeholder. Always ignored, exists for compatibility.
        candidates: Available placeholders in the source named by `context`.
        context: The source to which the `candidates` belong.
        regex: A regex pattern. Will be matched against elements of the `candidates`.
        remove: If ``True``, remove matching values.
        task_id: Used for logging.

    Returns:
        Placeholders that may be used.

    Examples:
        Removing irrelevant but possibly confusing columns.

        >>> actual_placeholders = {"id", "name", "old_id", "previous_id"}
        >>> allowed = filter_placeholders(
        ...     value="ignored",
        ...     candidates=actual_placeholders,
        ...     context="ignored",
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

    if _logging.ENABLE_VERBOSE_LOGGING and len(ans) < len(candidates):
        logger = logging.getLogger(__name__).getChild(filter_placeholders.__name__)
        if logger.isEnabledFor(logging.DEBUG):
            removed = candidates.difference(ans)
            logger.debug(
                f"Discard placeholders={removed!r} in source={context!r}; matches {pattern=}.",
                extra={"task_id": task_id},
            )

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
    *,
    task_id: int | None = None,
) -> bool:
    keep = (re.match(regex, string, re.IGNORECASE) is None) is remove

    if keep or not _logging.ENABLE_VERBOSE_LOGGING:
        return keep

    logger = logging.getLogger(__name__).getChild(function_name)
    if logger.isEnabledFor(logging.DEBUG):
        pattern = re.compile(regex, re.IGNORECASE)
        logger.debug(
            f"{action} {label}={string!r}; {'matches' if remove else 'does not match'} {pattern=}.",
            extra={"task_id": task_id},
        )

    return keep
