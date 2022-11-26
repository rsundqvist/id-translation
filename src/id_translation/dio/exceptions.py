"""Data structure I  exceptions."""

from typing import Any, Type


class DataStructureIOError(RuntimeError):
    """Base class for IO exceptions."""


class UntranslatableTypeError(DataStructureIOError):
    """Exception indicating that a type cannot be translated.

    Args:
        t: A type.
    """

    def __init__(self, t: Type[Any]) -> None:
        super().__init__(f"Type {t} cannot be translated.")


class NotInplaceTranslatableError(DataStructureIOError):
    """Exception indicating that a type cannot be translated in-place.

    Args:
        arg: Something that can't be translated inplace.
    """

    def __init__(self, arg: Any) -> None:
        super().__init__(f"Inplace translation not possible or implemented for type: {type(arg)}")
