"""Errors and warnings related to fetching."""

from collections.abc import Iterable as _Iterable
from typing import Any as _Any


class FetcherWarning(RuntimeWarning):
    """Base class for ``Fetcher`` warnings."""


class FetcherError(RuntimeError):
    """Base class for ``Fetcher`` exceptions."""


class ForbiddenOperationError(FetcherError):
    """Exception indicating that the ``Fetcher`` does not support an operation."""

    def __init__(self, operation: str, reason: str) -> None:
        super().__init__(f"Operation '{operation}' " + reason)
        self.operation = operation


class ImplementationError(FetcherError):
    """An underlying implementation did something wrong."""


class UnknownPlaceholderError(FetcherError):
    """Caller requested unknown placeholder name(s)."""


class UnknownIdError(FetcherError):
    """Caller requested unknown id(s)."""


class UnknownSourceError(FetcherError):
    """Caller requested unknown source(s).

    Args:
        unknown_sources: The sources which are not known to the Fetcher.
        sources: Sources known to the fetcher.
        msg: A format string that takes `unknown_sources` and `sources`.
    """

    def __init__(
        self,
        unknown_sources: _Iterable[_Any],
        sources: _Iterable[_Any],
        msg: str = "Sources {unknown_sources} not recognized. Known sources: {sources}.",
    ) -> None:
        self.sources = set(sources)
        self.unknown_sources = set(unknown_sources)
        super().__init__(msg.format(unknown_sources=self.unknown_sources, sources=self.sources))


class DuplicateSourceWarning(FetcherWarning):
    """Duplicate sources detected."""


class DuplicateSourceError(FetcherError):
    """Multiple translations for the same source received."""


class CacheAccessNotAvailableError(FetcherError):
    """Raised when calling :attr:`.AbstractFetcher.cache_access` on an instance that is not cached."""
