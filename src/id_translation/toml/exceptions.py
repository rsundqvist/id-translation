"""Errors raised by the TOML configuration layer, i.e. :meth:`Translator.from_config <id_translation.Translator.from_config>`."""

from collections.abc import Iterable as _Iterable

from .._utils import add_hints as _add_hints


class ConfigFileError(Exception):
    """A configuration file failed id-translation's own checks.

    Raised by :meth:`Translator.from_config <id_translation.Translator.from_config>` and the functions it uses, with a
    hint naming the file. Examples are an unknown key, a misplaced section, and a fetcher, transformer or cache section
    key that names a class that cannot be imported. The original error, if any, is the cause: the parser's error for a
    file that is not UTF-8 or not valid TOML, or has malformed interpolation syntax; the error that kept a section key
    from resolving, e.g. a :class:`ModuleNotFoundError` or an :class:`AttributeError`; or the :class:`TypeError` of a
    ``metaconf.toml`` check. It is also raised when every fetcher was discarded as optional; the logged errors say why.

    Errors raised by code the file names, or by the environment, are not wrapped. They propagate as themselves, with the
    same hint:

    * anything a fetcher, transformer or mapper raises when created, such as an :class:`ImportError` for a missing
      driver or an :class:`OSError` for a refused connection;
    * anything the :class:`~id_translation.Translator` class raises, such as a :class:`TypeError` for a bad
      ``[translator]`` argument;
    * an unset environment variable (:class:`rics.env.interpolation.UnsetVariableError`).

    A file that cannot be read raises an :class:`OSError` as is.

    A :attr:`~id_translation.toml.TranslatorFactory.FETCHER_FACTORY` or
    :attr:`~id_translation.toml.TranslatorFactory.TRANSFORMER_FACTORY` implementation may raise one for a section that
    breaks its own rules.

    Args:
        msg: The error message.
        hints: Additional context, attached as notes.
    """

    def __init__(self, msg: str, *, hints: str | _Iterable[str] = ()) -> None:
        super().__init__(msg)
        _add_hints(self, hints)
