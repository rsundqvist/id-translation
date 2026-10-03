"""Data structure IO exceptions."""

from collections.abc import Iterable as _Iterable
from typing import Any as _Any

from .._utils import add_hints as _add_hints


class DataStructureIOError(TypeError):
    """Base class for IO exceptions.

    Args:
        msg: The error message.
        hints: Hints to add as notes, after a link to the docs.
        anchor: Section of the :ref:`translation-io` page to link to.
    """

    def __init__(
        self,
        msg: str,
        *,
        hints: str | _Iterable[str] = (),
        anchor: str = "user-defined-integrations",
    ) -> None:
        super().__init__(msg)

        from id_translation._utils import DOC_LINK  # noqa: PLC0415

        url = DOC_LINK + f"documentation/translation-io.html#{anchor}"
        self.add_note(f"Hint: {url}")

        _add_hints(self, hints)


class UntranslatableTypeError(DataStructureIOError):
    """Exception indicating that a type cannot be translated.

    Args:
        t: A type.
    """

    def __init__(self, t: type[_Any], *, hints: str | _Iterable[str] = ()) -> None:
        super().__init__(f"Type {t} cannot be translated.", hints=hints)


class NotInplaceTranslatableError(DataStructureIOError):
    """Exception indicating that a type cannot be translated in-place.

    Args:
        arg: Something that can't be translated inplace.
    """

    def __init__(self, arg: _Any) -> None:
        super().__init__(f"Inplace translation not possible or implemented for type: {type(arg)}")


class RegistryReentryError(DataStructureIOError):
    """The IO registry was used while it was loading the ``id_translation.dio`` entrypoint integrations.

    Typically raised when a module loaded as an entrypoint calls :meth:`~id_translation.dio.DataStructureIO.register`
    at import time. Not an ``ImportError``, so that optional-import guards in the entrypoint module do not swallow it.
    """
