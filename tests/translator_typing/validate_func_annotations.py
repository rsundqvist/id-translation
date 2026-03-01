import sys
from collections.abc import Callable
from typing import Any, Optional, Required, get_args, get_origin

from rics.misc import tname

if sys.version_info < (3, 14):

    def get_annotations(func: Any) -> dict[str, Any]:
        return {**func.__annotations__}
else:
    # TODO(python-3.14): Remove conditional import.
    from annotationlib import get_annotations

_AnyCallable = Callable[..., Any]
_NOTHING = "<nothing>"
_ErrorTuple = tuple[str, Any, Any]


def validate_func_annotations(
    func: _AnyCallable,
    annotations: Any,
    exclude: set[str] | None = None,
    fail_fast: bool = True,
) -> None:
    """Validate the signature of `func` against the given ``TypedDict``.

    Args:
        func: The function to validate.
        annotations: A type with ``__annotations__``, such as a ``TypedDict``.
        exclude: Keys to exclude. Default is `'self'` and `'cls'`.
        fail_fast: Set to ``True`` to raise on the first error.

    Raises:
        ValidationError: For single errors.
        MultipleValidationError: For multiple errors (when ``fail_fast=False``).
    """
    func_name = tname(func, prefix_classname=True, include_module=True)

    if isinstance(func, type):
        msg = f"use `{func_name}.__init__` instead"
        raise TypeError(msg)
    if not callable(func):
        msg = f"{func_name} must be callable"
        raise TypeError(msg)

    expected_dict = get_annotations(func)
    expected_dict.pop("return")
    actual_dict = get_annotations(annotations)

    if exclude is None:
        expected_dict.pop("self", None)
        expected_dict.pop("cls", None)
    else:
        for key in exclude:
            expected_dict.pop(key)

    errors: list[_ErrorTuple] = []

    all_keys = {*expected_dict, *actual_dict}
    for key in sorted(all_keys):
        actual = actual_dict.get(key, _NOTHING)
        expected = expected_dict.get(key, _NOTHING)

        origin = get_origin(actual)
        if origin is Required or origin is Optional:
            actual = get_args(actual)[0]

        if actual != expected:
            err = (key, actual, expected)
            if fail_fast:
                raise ValidationError(err, func_name)

            errors.append(err)

    if errors:
        if len(errors) == 1:
            raise ValidationError(errors[0], func_name)
        else:
            raise MultipleValidationError(func_name, errors)


def _format_error(key: str, actual: Any, expected: Any, func_name: str | None = None) -> str:
    issue = f"Expected `{expected}` but found `{actual}`"
    return f"{key}: {issue}" if func_name is None else f"{func_name}({key}): {issue}"


class MultipleValidationError(Exception):
    """Raised by :func:`validate_func_annotations`."""

    def __init__(self, func_name: str, errors: list[_ErrorTuple]) -> None:
        super().__init__(func_name, len(errors))

        for err in errors:
            self.add_note(_format_error(*err))

    def __str__(self) -> str:
        return f"{self.args[0]}: Found {self.args[1]} errors."


class ValidationError(Exception):
    """Raised by :func:`validate_func_annotations`."""

    def __init__(self, err: _ErrorTuple, func_name: str) -> None:
        super().__init__(*err, func_name)

    def __str__(self) -> str:
        return _format_error(*self.args)
