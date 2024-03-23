"""Global translation settings."""

import logging as _l
import typing as _t


class KeyEventLogLevel(_t.NamedTuple):
    """Enter/exit log level pair for key events. Default level is 10 ``logging.DEBUG=10``."""

    enter: int = _l.DEBUG
    """Log level for the ``ENTER`` message, e.g. ``TRANSLATOR.TRANSLATE.ENTER``.

    .. code-block:: python
       :caption: Example: Enter message of the :meth:`.Translator.translate`-method.

       Begin translation of 'DataFrame'-type data. Names to translate: Derive
         based on type='DataFrame'.
    """

    exit: int = _l.DEBUG
    """Log level for the ``EXIT`` message, e.g. ``TRANSLATOR.TRANSLATE.EXIT``.

    .. code-block:: python
       :caption: Example: Exit message of the :meth:`.Translator.translate`-method.

       Finished translation of 4 names in 'DataFrame'-type data in 133 ms,
         using name-to-source mapping: {'customer_id': 'customer', 'film_id':
         'film', 'category_id': 'category', 'staff_id': 'staff'}.
    """


class logging:  # noqa: N801
    """Global logging settings used by all instances."""

    TRANSLATE_ONLINE: KeyEventLogLevel = KeyEventLogLevel(exit=_l.INFO)
    """Levels for ``TRANSLATOR.TRANSLATE`` key event messages when the :class:`.Translator` is :attr:`~.Translator.online`."""
    TRANSLATE_OFFLINE: KeyEventLogLevel = KeyEventLogLevel()
    """Levels for ``TRANSLATOR.TRANSLATE`` key event messages when the :class:`.Translator` is offline."""
    MAP: KeyEventLogLevel = KeyEventLogLevel()
    """Levels for ``TRANSLATOR.MAP`` key event messages."""

    MAP_PLACEHOLDERS: KeyEventLogLevel = KeyEventLogLevel()
    """Levels for ``FETCHER.MAP_PLACEHOLDERS`` key event messages."""
    FETCH_TRANSLATIONS: KeyEventLogLevel = KeyEventLogLevel()
    """Levels for ``FETCHER.FETCH_TRANSLATIONS`` key event messages."""

    MULTI_FETCH: KeyEventLogLevel = KeyEventLogLevel()
    """Levels for ``MULTIFETCHER.FETCH`` key event messages."""
    MULTI_FETCH_ALL: KeyEventLogLevel = KeyEventLogLevel()
    """Levels for ``MULTIFETCHER.FETCH_ALL`` key event messages."""

    def __init__(self) -> None:
        _raise_info_message(self)


def _raise_info_message(obj: _t.Any) -> None:
    from rics.misc import get_public_module, tname

    raise RuntimeError(
        f"Class '{get_public_module(obj)}.{tname(obj)}' is used as a public"
        f" namespace. There is no need to instantiate this class."
    )
