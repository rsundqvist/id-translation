"""Mapping errors."""
from typing import Any, Set


class MappingError(ValueError):
    """Something failed to map."""

    def __init__(self, msg: str) -> None:
        super().__init__(
            msg + "\n\nFor help, please refer to the "
            "https://rics.readthedocs.io/en/stable/documentation/mapping-primer.html page."
        )


class ScoringDisabledError(MappingError):
    """Indicates that the scoring logic has been disabled. Raised by :func:`.score_functions.disabled`."""

    def __init__(self, value: Any, candidates: Any, context: Any) -> None:
        super().__init__(
            "Scoring disabled; the Mapper is working in override-only mode. Please add an override "
            f"for {value=} in {context=} in order to map it to an appropriate candidate."
        )
        self.value = value
        self.candidates = candidates
        self.context = context


class AmbiguousScoreError(MappingError):
    """Indicates that the scoring logic has produces ambiguous scores."""

    def __init__(self, kind: str, key: Any, match0: Any, match1: Any, cardinality: str, scores: str) -> None:
        hint = f"\n{scores}\nInspect the matrix above for details. You may wish to use a different scoring method."
        super().__init__(
            f"Ambiguous mapping of {kind}={key!r}; matches ({match0}) and ({match1}) "
            f"are in conflict since {cardinality=}.{hint}"
        )


class UserMappingError(MappingError):
    """A user-defined mapping function did something forbidden."""

    def __init__(self, msg: str, value: Any, candidates: Set[Any]) -> None:
        super().__init__(msg)
        self.value = value
        self.candidates = candidates


class CardinalityError(MappingError):
    """Base class for cardinality issues."""


class MappingWarning(UserWarning):
    """Something failed to map."""


class UserMappingWarning(MappingWarning):
    """A user-defined mapping function did something strange."""


class BadFilterError(MappingError):
    """Invalid filter."""
