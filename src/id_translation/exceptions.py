"""General errors for the translation suite.

Every exception and warning in the suite takes the message as its first argument, followed by optional keyword-only
data such as ``hints``. List-like data is stored as a tuple, and a bare string counts as one item. Exceptions that
carry data and that implementations outside the suite are expected to raise also have a ``for_*`` classmethod, which
takes the data and formats the standard message with names sorted. The classmethod is named for what its first
argument holds, and every later argument is keyword-only. For example,
:meth:`~id_translation.fetching.exceptions.UnknownPlaceholderError.for_placeholders` takes the unknown placeholders.
"""

from collections.abc import Iterable as _Iterable
from typing import Any as _Any

from ._utils import add_hints as _add_hints
from ._utils import as_tuple as _as_tuple


class ConfigurationError(TypeError):
    """Raised in case of bad configuration."""

    def __init__(self, msg: str, *, hints: str | _Iterable[str] = ()) -> None:
        super().__init__(msg)
        _add_hints(self, hints)


class ConfigurationChangedError(Exception):
    """See :meth:`Translator.load_persistent_instance <id_translation.Translator.load_persistent_instance>`."""

    def __init__(self, msg: str, *, hints: str | _Iterable[str] = ()) -> None:
        super().__init__(msg)
        _add_hints(self, hints)


class ConnectionStatusError(ConnectionError):
    """Raised when trying to perform operations in a bad online/offline state."""

    # Keep the `ConnectionError`/`OSError` base -- it's deliberate (see 0.8.0 changelog) so callers can catch generic
    # connection errors; the two/three-arg `OSError(errno, strerror[, filename])` form is not supported and isn't
    # expected to be used here.

    def __init__(self, msg: str, *, hints: str | _Iterable[str] = ()) -> None:
        super().__init__(msg)
        _add_hints(self, hints)


class TranslationError(Exception):
    """Base class for translation errors."""

    def __init__(self, msg: str, *, hints: str | _Iterable[str] = ()) -> None:
        super().__init__(msg)
        _add_hints(self, hints)


class MissingNamesError(TranslationError):
    """Raised if names could not be derived based on the data type, and aren't explicitly given."""


class TooManyFailedTranslationsError(TranslationError):
    """Raised if too many IDs fail to translate.

    Args:
        msg: The error message.
        name: The name whose IDs failed to translate.
        source: The source that `name` was mapped to.
        n_untranslated: Number of IDs that failed to translate.
        n_total: Number of IDs, including those that failed.
        max_fails: The highest fraction of failed IDs that was allowed.
        sample_ids: Some of the IDs that failed to translate.
        hints: Additional context, attached as notes.
    """

    def __init__(
        self,
        msg: str,
        *,
        name: _Any = None,
        source: _Any = None,
        n_untranslated: int | None = None,
        n_total: int | None = None,
        max_fails: float | None = None,
        sample_ids: _Iterable[_Any] = (),
        hints: str | _Iterable[str] = (),
    ) -> None:
        super().__init__(msg, hints=hints)
        self.name = name
        self.source = source
        self.n_untranslated = n_untranslated
        self.n_total = n_total
        self.max_fails = max_fails
        self.sample_ids = _as_tuple(sample_ids)


class MissingPlaceholderError(ValueError):
    """A source lacks placeholders that are required, e.g. by the translation format.

    Raised wherever this is detected. :class:`~id_translation.fetching.exceptions.UnknownPlaceholderError` is the
    subclass fetchers may raise; a missing ``id`` is a :class:`~id_translation.exceptions.MissingIdPlaceholderError`.

    Args:
        msg: The error message.
        missing_placeholders: Required placeholder names that `source` does not have. A single name may be given as a
            string.
        placeholders: Placeholder names that `source` does have. A single name may be given as a string.
        source: The source that lacks the placeholders.
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
        super().__init__(msg)
        self.missing_placeholders = _as_tuple(missing_placeholders)
        self.placeholders = _as_tuple(placeholders)
        self.source = source
        _add_hints(self, hints)


class MissingIdPlaceholderError(MissingPlaceholderError):
    """A source has no ``id`` placeholder, so its translations cannot be keyed by ID.

    Raised wherever this is detected. Inline data, such as a ``dict`` given to the ``Translator`` or a
    ``TranslationMap``, is not mapped, so it raises at construction without a placeholder literally named ``id``.
    Fetchers raise the :class:`~id_translation.fetching.exceptions.UnknownIdPlaceholderError` subclass.

    Args:
        msg: The error message.
        source: The source without an ``id`` placeholder.
        placeholders: Placeholder names that `source` does have. A single name may be given as a string.
        hints: Additional context, attached as notes.
    """

    def __init__(
        self,
        msg: str,
        *,
        source: _Any = None,
        placeholders: _Iterable[str] | str = (),
        hints: str | _Iterable[str] = (),
    ) -> None:
        super().__init__(msg, missing_placeholders="id", placeholders=placeholders, source=source, hints=hints)


class TransformerConflictError(ValueError):
    """A source already has a transformer, and ``on_existing='raise'``.

    See :meth:`Translator.register_transformer <id_translation.Translator.register_transformer>`.
    """

    # Keep the `ValueError` base -- it's deliberate: registration's sibling failures (an empty chain, a
    # non-Transformer value) raise ValueError/TypeError, so `except ValueError` around a registration block
    # catches the conflict too.

    def __init__(self, msg: str, *, hints: str | _Iterable[str] = ()) -> None:
        super().__init__(msg)
        _add_hints(self, hints)


class IdTranslationWarning(Warning):
    """Base class for all warnings emitted by ``id-translation``.

    A single filter covers every warning in the suite::

        warnings.filterwarnings("ignore", category=IdTranslationWarning)
    """


class TranslationWarning(IdTranslationWarning):
    """Base class for translation warnings."""


class TranslationAbortedWarning(TranslationWarning):
    """Translation was aborted.

    Emitted when no derived names are mapped to sources.
    """


class TranslationDisabledWarning(TranslationWarning):
    """Translation is globally disabled.

    Emitted when :envvar:`ID_TRANSLATION_DISABLED` is set.
    """
