"""General errors for the translation suite."""


class ConfigurationError(ValueError):
    """Raised in case of bad configuration."""


class ConnectionStatusError(ValueError):
    """Raised when trying to perform operations in a bad online/offline state."""


class TranslationError(ValueError):
    """Base class for translation errors."""


class TooManyFailedTranslationsError(TranslationError):
    """Raised if too many IDs fail to translate."""
