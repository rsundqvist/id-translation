"""General errors for the translation suite."""

from collections.abc import Iterable as _Iterable
from warnings import simplefilter as _simplefilter

from ._utils import add_hints as _add_hints


class ConfigurationError(TypeError):
    """Raised in case of bad configuration."""


class ConfigurationChangedError(Exception):
    """See :meth:`Translator.load_persistent_instance <id_translation.Translator.load_persistent_instance>`."""


class ConnectionStatusError(ConnectionError):
    """Raised when trying to perform operations in a bad online/offline state."""

    # TODO(2.0.0): Drop the `msg` default; it exists only to keep zero-arg `raise ConnectionStatusError()` calls
    #  working after `msg` became a real constructor arg. Keep the `ConnectionError`/`OSError` base -- it's
    #  deliberate (see 0.8.0 changelog) so callers can catch generic connection errors; the two/three-arg
    #  `OSError(errno, strerror[, filename])` form is not supported and isn't expected to be used here.

    def __init__(self, msg: str = "", *, hints: str | _Iterable[str] = ()) -> None:
        super().__init__(msg)
        _add_hints(self, hints)


class TranslationError(Exception):
    """Base class for translation errors."""

    # TODO(2.0.0): Inherit from a common `IdTranslationError` shared by all id-translation exceptions.
    # TODO(2.0.0): Drop the `msg` default; it exists only to keep zero-arg `raise TranslationError()`-style calls
    #  working after `msg` became a real constructor arg.

    def __init__(self, msg: str = "", *, hints: str | _Iterable[str] = ()) -> None:
        super().__init__(msg)
        _add_hints(self, hints)


class MissingNamesError(TranslationError):
    """Raised if names could not be derived based on the data type, and aren't explicitly given."""


class TooManyFailedTranslationsError(TranslationError):
    """Raised if too many IDs fail to translate."""


class TransformerConflictError(ValueError):
    """A source already has a transformer, and ``on_existing='raise'``.

    See :meth:`Translator.register_transformer <id_translation.Translator.register_transformer>`.
    """

    # Keep the `ValueError` base -- it's deliberate: registration's sibling failures (an empty chain, a
    # non-Transformer value) raise ValueError/TypeError, so `except ValueError` around a registration block
    # catches the conflict too.
    # TODO(2.0.0): Also inherit the common `IdTranslationError` planned for `TranslationError` above.


class TranslationWarning(UserWarning):
    """Base class for translation warnings."""


class TranslationAbortedWarning(TranslationWarning):
    """Translation was aborted.

    Emitted when no derived names are mapped to sources.
    """


class TranslationDisabledWarning(TranslationWarning):
    """Translation is globally disabled.

    Emitted when :envvar:`ID_TRANSLATION_DISABLED` is set.
    """


_simplefilter("once", category=TranslationDisabledWarning)
