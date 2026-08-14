"""Data structure IO exceptions."""

from collections.abc import Iterable as _Iterable
from typing import Any as _Any

from .._utils import add_hints as _add_hints


class DataStructureIOError(TypeError):
    """Base class for IO exceptions."""

    # TODO(2.0.0): Inherit from a common `IdTranslationError` shared by all id-translation exceptions.

    def __init__(self, msg: str, *, hints: str | _Iterable[str] = ()) -> None:
        super().__init__(msg)

        from id_translation._utils import DOC_LINK  # noqa: PLC0415

        url = DOC_LINK + "api/id_translation.dio.html#user-defined-integrations"
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
