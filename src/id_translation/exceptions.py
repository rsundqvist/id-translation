"""General errors for the translation suite."""
from warnings import simplefilter as _simplefilter


class ConfigurationError(ValueError):
    """Raised in case of bad configuration."""


class ConnectionStatusError(ValueError):
    """Raised when trying to perform operations in a bad online/offline state."""


class TranslationError(ValueError):
    """Base class for translation errors."""


class TooManyFailedTranslationsError(TranslationError):
    """Raised if too many IDs fail to translate."""


class TranslationWarning(UserWarning):
    """Base class for translation warnings."""


class TranslationDisabledWarning(TranslationWarning):
    """Translation is globally disabled."""


_simplefilter("once", category=TranslationDisabledWarning)
