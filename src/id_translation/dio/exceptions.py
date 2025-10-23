"""Data structure IO exceptions."""

from typing import Any as _Any


class DataStructureIOError(TypeError):
    """Base class for IO exceptions."""

    _url = "https://id-translation.readthedocs.io/en/stable/api/id_translation.dio.html#user-defined-integrations"

    def __init__(self, msg: str) -> None:
        super().__init__(msg)
        self.add_note(f"Hint: {self._url}")


class UntranslatableTypeError(DataStructureIOError):
    """Exception indicating that a type cannot be translated.

    Args:
        t: A type.
    """

    def __init__(self, t: type[_Any]) -> None:
        super().__init__(f"Type {t} cannot be translated.")


class NotInplaceTranslatableError(DataStructureIOError):
    """Exception indicating that a type cannot be translated in-place.

    Args:
        arg: Something that can't be translated inplace.
    """

    def __init__(self, arg: _Any) -> None:
        super().__init__(f"Inplace translation not possible or implemented for type: {type(arg)}")
