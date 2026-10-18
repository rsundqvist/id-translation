"""Errors and warnings related to fetching."""

from collections.abc import Iterable as _Iterable
from typing import TYPE_CHECKING
from typing import Any as _Any
from typing import Self as _Self

from .._utils import add_hints as _add_hints
from .._utils import as_tuple as _as_tuple
from ..exceptions import IdTranslationWarning as _IdTranslationWarning

if TYPE_CHECKING:
    from ._fetcher import Fetcher


class FetcherWarning(_IdTranslationWarning):
    """Base class for ``Fetcher`` warnings."""


class ConcurrentOperationWarning(FetcherWarning):
    """A thread-unsafe ``Fetcher`` operation was entered from multiple threads at once.

    Use :meth:`~id_translation.fetching.exceptions.ConcurrentOperationWarning.for_operation` to build the
    standard message.

    Args:
        msg: The warning message.
        operation: The thread-unsafe operation that was entered concurrently.
        fetcher_class: Class name of the emitting implementation, e.g. `SqlFetcher`;
            module-qualified for a class outside ``id_translation.fetching``.
    """

    def __init__(self, msg: str, *, operation: str = "", fetcher_class: str = "") -> None:
        super().__init__(msg)
        self.operation = operation
        self.fetcher_class = fetcher_class

    @classmethod
    def for_operation(cls, operation: str, *, fetcher_class: str) -> _Self:
        """Create a warning with the standard message."""
        return cls(
            f"Concurrent operation detected in {fetcher_class}.{operation}().",
            operation=operation,
            fetcher_class=fetcher_class,
        )


class FetcherError(RuntimeError):
    """Base class for ``Fetcher`` exceptions."""

    def __init__(self, msg: str, *, hints: str | _Iterable[str] = ()) -> None:
        super().__init__(msg)
        _add_hints(self, hints)


class ForbiddenOperationError(FetcherError):
    """Exception indicating that the ``Fetcher`` does not support an operation.

    Use :meth:`~id_translation.fetching.exceptions.ForbiddenOperationError.for_operation` to build the
    standard message.

    Args:
        msg: The error message.
        operation: The operation that is not supported.
        fetcher_class: Class name of the raising implementation, e.g. `SqlFetcher`;
            module-qualified for a class outside ``id_translation.fetching``.
        hints: Additional context, attached as notes.
    """

    def __init__(
        self,
        msg: str,
        *,
        operation: str = "",
        fetcher_class: str = "",
        hints: str | _Iterable[str] = (),
    ) -> None:
        super().__init__(msg, hints=hints)
        self.operation = operation
        self.fetcher_class = fetcher_class

    @classmethod
    def for_operation(cls, operation: str, *, fetcher_class: str, hints: str | _Iterable[str] = ()) -> _Self:
        """Create an error with the standard message.

        Args:
            operation: The operation that is not supported.
            fetcher_class: Class name of the raising implementation, e.g. `SqlFetcher`;
                module-qualified for a class outside ``id_translation.fetching``.
            hints: Additional context, attached as notes.

        Returns:
            A new error.
        """
        return cls(
            f"Operation {operation!r} is not permitted by {fetcher_class}.",
            operation=operation,
            fetcher_class=fetcher_class,
            hints=hints,
        )


class ImplementationError(FetcherError):
    """An underlying implementation did something wrong."""


class UnknownPlaceholderError(FetcherError):
    """Caller requested unknown placeholder name(s).

    Use :meth:`~id_translation.fetching.exceptions.UnknownPlaceholderError.for_placeholders` to build the
    standard message.

    Args:
        msg: The error message.
        missing_placeholders: Placeholder names that `source` does not have. A single name may be given as a string.
        placeholders: Placeholder names that `source` does have. A single name may be given as a string.
        source: The source that was searched.
        hints: Additional context, attached as notes.
    """

    def __init__(
        self,
        msg: str,
        *,
        missing_placeholders: _Iterable[str] | str = (),
        placeholders: _Iterable[str] | str = (),
        source: _Any = None,
        hints: str | _Iterable[str] = (),
    ) -> None:
        super().__init__(msg, hints=hints)
        self.missing_placeholders = _as_tuple(missing_placeholders)
        self.placeholders = _as_tuple(placeholders)
        self.source = source

    @classmethod
    def for_placeholders(
        cls,
        missing_placeholders: _Iterable[str] | str,
        *,
        placeholders: _Iterable[str] | str,
        source: _Any,
        caller: "Fetcher[_Any, _Any]",
        hints: str | _Iterable[str] = (),
    ) -> _Self:
        """Create an error with the standard message.

        Args:
            missing_placeholders: Placeholder names that `source` does not have. A single name may be given as a string.
            placeholders: Placeholder names that `source` does have. A single name may be given as a string.
            source: The source that was searched.
            caller: The fetcher raising the error. Rendered with its
                :attr:`~id_translation.fetching.AbstractFetcher.config_file` when it has one.
            hints: Additional context, attached as notes.

        Returns:
            A new error.
        """
        missing_placeholders = _as_tuple(missing_placeholders)
        placeholders = _as_tuple(placeholders)
        msg = (
            f"Placeholders {sorted(missing_placeholders)} not recognized by {_render_caller(caller)}."
            f" For source={source!r}, known placeholders are: {sorted(placeholders)}."
        )
        return cls(
            msg, missing_placeholders=missing_placeholders, placeholders=placeholders, source=source, hints=hints
        )


class UnknownSourceError(FetcherError):
    """Caller requested unknown source(s).

    Use :meth:`~id_translation.fetching.exceptions.UnknownSourceError.for_sources` to build the
    standard message.

    Args:
        msg: The error message.
        unknown_sources: The sources which are not known to the Fetcher. A single source may be given as a string.
        sources: Sources known to the fetcher. A single source may be given as a string.
        hints: Additional context, attached as notes.
    """

    def __init__(
        self,
        msg: str,
        *,
        unknown_sources: _Iterable[_Any] | str = (),
        sources: _Iterable[_Any] | str = (),
        hints: str | _Iterable[str] = (),
    ) -> None:
        super().__init__(msg, hints=hints)
        self.unknown_sources = _as_tuple(unknown_sources)
        self.sources = _as_tuple(sources)

    @classmethod
    def for_sources(
        cls,
        unknown_sources: _Iterable[_Any] | str,
        *,
        sources: _Iterable[_Any] | str,
        hints: str | _Iterable[str] = (),
    ) -> _Self:
        """Create an error with the standard message.

        Args:
            unknown_sources: The sources which are not known to the Fetcher. A single source may be given as a string.
            sources: Sources known to the fetcher. A single source may be given as a string.
            hints: Additional context, attached as notes.

        Returns:
            A new error.
        """
        unknown_sources = _as_tuple(unknown_sources)
        sources = _as_tuple(sources)
        msg = f"Sources {sorted(unknown_sources, key=str)} not recognized. Known sources: {sorted(sources, key=str)}."
        return cls(msg, unknown_sources=unknown_sources, sources=sources, hints=hints)


class DuplicateSourceWarning(FetcherWarning):
    """Duplicate sources detected."""


class DuplicateSourceError(FetcherError):
    """Multiple translations for the same source received.

    Args:
        msg: The error message.
        source: The source that was received more than once.
        hints: Additional context, attached as notes.
    """

    def __init__(self, msg: str, *, source: _Any = None, hints: str | _Iterable[str] = ()) -> None:
        super().__init__(msg, hints=hints)
        self.source = source


class CacheAccessNotAvailableError(FetcherError):
    """Raised by :attr:`AbstractFetcher.cache_access <id_translation.fetching.AbstractFetcher.cache_access>` on instances that are not cached."""

    def __init__(self, msg: str, *, hints: str | _Iterable[str] = ()) -> None:
        super().__init__(msg, hints=hints)

        from id_translation._utils import DOC_LINK  # noqa: PLC0415

        link = DOC_LINK + "documentation/examples/caching/on_disk.html"
        self.add_note(f"Hint: {link}")


def _render_caller(caller: "Fetcher[_Any, _Any]") -> str:
    config_file = getattr(caller, "config_file", None)
    return f"{type(caller).__name__} (configured in {config_file!r})" if config_file else str(caller)
