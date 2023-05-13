"""Mapping errors."""
from typing import Any, Set


class MappingError(ValueError):
    """Something failed to map."""

    def __init__(self, msg: str, ref: str = "") -> None:
        link = "https://id-translation.readthedocs.io/en/stable/documentation/mapping-primer.html"
        if ref:
            link += f"#{ref}"
        super().__init__(f"{msg}\n\nFor help, please refer to the {link} page.")


class ScoringDisabledError(MappingError):
    """Indicates that the scoring logic has been disabled. Raised by :func:`.score_functions.disabled`."""

    def __init__(self, value: Any, candidates: Any, context: Any) -> None:
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
