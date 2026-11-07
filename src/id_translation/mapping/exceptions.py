"""Mapping errors."""

from collections.abc import Iterable as _Iterable
from typing import Any as _Any

from .._utils import add_hints as _add_hints
from .._utils import as_tuple as _as_tuple
from ..exceptions import IdTranslationWarning as _IdTranslationWarning


class MappingError(Exception):
    """Base exception class for all mapping-related issues."""

    def __init__(self, msg: str, *, ref: str = "", hints: str | _Iterable[str] = ()) -> None:
        super().__init__(msg)

        from id_translation._utils import DOC_LINK  # noqa: PLC0415

        link = DOC_LINK + "documentation/mapping-primer.html"
        if ref:
            link += f"#{ref}"
        self.add_note(f"Hint: See {link} for help.")

        func = "id_translation.logging.enable_verbose_debug_messages"
        if __debug__:
            from id_translation.logging import enable_verbose_debug_messages  # noqa: PLC0415

            expected = enable_verbose_debug_messages.__module__ + "." + enable_verbose_debug_messages.__name__
            assert func == expected  # noqa: S101
        self.add_note(f"Hint: Use `{func}` to see why mapping failed.")

        _add_hints(self, hints)


class UnmappedValuesError(MappingError):
    """Raised when there are unmapped values left after filtering and on_unmapped='raise'.

    Args:
        msg: The error message.
        unmapped: Values that could not be mapped. A single value may be given as a string.
        hints: Additional context, attached as notes.
    """

    def __init__(self, msg: str, *, unmapped: _Iterable[_Any] | str = (), hints: str | _Iterable[str] = ()) -> None:
        super().__init__(msg, hints=hints)
        self.unmapped = _as_tuple(unmapped)


class UnmappedExplicitNamesError(UnmappedValuesError):
    """Raised when names explicitly provided by the user could not be mapped.

    Args:
        msg: The error message.
        names: Names explicitly provided by the user. A single name may be given as a string.
        unmapped: Elements of `names` that could not be mapped. A single name may be given as a string.
        hints: Additional context, attached as notes.
    """

    def __init__(
        self,
        msg: str,
        *,
        names: _Iterable[_Any] | str = (),
        unmapped: _Iterable[_Any] | str = (),
        hints: str | _Iterable[str] = (),
    ) -> None:
        super().__init__(msg, unmapped=unmapped, hints=hints)
        self.names = _as_tuple(names)

        self.add_note("Note: This error is NOT controlled by the `Mapper.on_unmapped` property.")
        if self.unmapped:
            self.add_note(
                f"Hint: Remove {len(self.unmapped)} unmapped name(s) from the provided names={list(self.names)}"
                " to continue."
            )


class ScoringDisabledError(MappingError):
    """Indicates that the scoring logic has been disabled.

    Raised by :func:`score_functions.disabled <id_translation.mapping.score_functions.disabled>`.

    Args:
        msg: The error message.
        value: The value that could not be mapped.
        candidates: Candidates that `value` could have been mapped to. A single candidate may be given as a string.
        context: Context in which mapping was attempted.
        hints: Additional context, attached as notes.
    """

    def __init__(
        self,
        msg: str,
        *,
        value: _Any = None,
        candidates: _Iterable[_Any] | str = (),
        context: _Any = None,
        hints: str | _Iterable[str] = (),
    ) -> None:
        super().__init__(msg, ref="override-only-mapping", hints=hints)
        self.value = value
        self.candidates = _as_tuple(candidates)
        self.context = context


class AmbiguousScoreError(MappingError):
    """Indicates that the scoring logic has produced ambiguous scores."""


class UserMappingError(MappingError):
    """A user-defined mapping function did something forbidden.

    Args:
        msg: The error message.
        value: The value that was being mapped.
        candidates: Candidates that `value` could be mapped to. A single candidate may be given as a string.
        hints: Additional context, attached as notes.
    """

    def __init__(
        self,
        msg: str,
        *,
        value: _Any = None,
        candidates: _Iterable[_Any] | str = (),
        hints: str | _Iterable[str] = (),
    ) -> None:
        super().__init__(msg, hints=hints)
        self.value = value
        self.candidates = _as_tuple(candidates)


class CardinalityError(MappingError):
    """Base class for cardinality issues."""


class MappingWarning(_IdTranslationWarning):
    """Base warning class for all mapping-related issues."""


class UnmappedValuesWarning(MappingWarning):
    """Raised when there are unmapped values left after filtering and on_unmapped='warn'."""


class UserMappingWarning(MappingWarning):
    """A user-defined mapping function did something strange."""


class BadFilterError(MappingError):
    """Invalid filter."""
