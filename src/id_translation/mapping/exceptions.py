"""Mapping errors."""

from typing import Any as _Any


class MappingError(Exception):
    """Base exception class for all mapping-related issues."""

    def __init__(self, msg: str, *, ref: str = "") -> None:
        super().__init__(msg)

        link = "https://id-translation.readthedocs.io/en/stable/documentation/mapping-primer.html"
        if ref:
            link += f"#{ref}"
        self.add_note(f"Hint: See {link} for help.")

        func = "id_translation.logging.enable_verbose_debug_messages"
        if __debug__:
            from id_translation.logging import enable_verbose_debug_messages  # noqa: PLC0415

            expected = enable_verbose_debug_messages.__module__ + "." + enable_verbose_debug_messages.__name__
            assert func == expected  # noqa: S101
        self.add_note(f"Hint: Use `{func}` for detailed output.")


class UnmappedValuesError(MappingError):
    """Raised when there are unmapped values left after filtering and on_unmapped='raise'."""


class ScoringDisabledError(MappingError):
    """Indicates that the scoring logic has been disabled. Raised by :func:`.score_functions.disabled`."""

    def __init__(self, value: _Any, candidates: _Any, context: _Any) -> None:
        super().__init__(
            "Scoring disabled.\n"
            f"The Mapper is working in strict override-only mode, so the {value=} in {context=} "
            f"cannot be mapped to any of the {candidates=}. Possible solutions:\n"
            "    * Add an override or filter for this value, or\n"
            "    * Set strict=False (silently refuse to map instead of raising), or\n"
            "    * Choose an appropriate score function to use.",
            ref="override-only-mapping",
        )
        self.value = value
        self.candidates = candidates
        self.context = context


class AmbiguousScoreError(MappingError):
    """Indicates that the scoring logic has produces ambiguous scores."""

    def __init__(self, kind: str, key: _Any, match0: _Any, match1: _Any, cardinality: str, scores: str) -> None:
        hint = f"\n{scores}\nInspect the matrix above for details. You may wish to use a different scoring method."
        super().__init__(
            f"Ambiguous mapping of {kind}={key!r}; matches ({match0}) and ({match1}) "
            f"are in conflict since {cardinality=}.{hint}"
        )


class UserMappingError(MappingError):
    """A user-defined mapping function did something forbidden."""

    def __init__(self, msg: str, value: _Any, candidates: set[_Any]) -> None:
        super().__init__(msg)
        self.value = value
        self.candidates = candidates


class CardinalityError(MappingError):
    """Base class for cardinality issues."""


class MappingWarning(UserWarning):
    """Base warning class for all mapping-related issues."""


class UnmappedValuesWarning(MappingWarning):
    """Raised when there are unmapped values left after filtering and on_unmapped='raise'."""


class UserMappingWarning(MappingWarning):
    """A user-defined mapping function did something strange."""


class BadFilterError(MappingError):
    """Invalid filter."""
