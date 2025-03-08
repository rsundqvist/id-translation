"""General errors for the translation suite."""

from warnings import simplefilter as _simplefilter


class ConfigurationError(TypeError):
    """Raised in case of bad configuration."""


class ConfigurationChangedError(Exception):
    """See :meth:`.Translator.load_persistent_instance`."""


class ConnectionStatusError(ConnectionError):
    """Raised when trying to perform operations in a bad online/offline state."""


class TranslationError(Exception):
    """Base class for translation errors."""


class MissingNamesError(TranslationError):
    """Raised if names could not be derived based on the data type, and aren't explicitly given."""


class TooManyFailedTranslationsError(TranslationError):
    """Raised if too many IDs fail to translate."""


class TranslationWarning(UserWarning):
    """Base class for translation warnings."""


class TranslationDisabledWarning(TranslationWarning):
    """Translation is globally disabled."""


_simplefilter("once", category=TranslationDisabledWarning)
