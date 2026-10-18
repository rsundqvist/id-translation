"""Data structure IO exceptions."""

from collections.abc import Iterable as _Iterable
from typing import Any as _Any
from typing import Self as _Self

from .._utils import add_hints as _add_hints


class DataStructureIOError(TypeError):
    """Base class for IO exceptions."""

    def __init__(self, msg: str, *, hints: str | _Iterable[str] = ()) -> None:
        super().__init__(msg)

        from id_translation._utils import DOC_LINK  # noqa: PLC0415

        url = DOC_LINK + "api/id_translation.dio.html#user-defined-integrations"
        self.add_note(f"Hint: {url}")

        _add_hints(self, hints)


class UntranslatableTypeError(DataStructureIOError):
    """Exception indicating that a type cannot be translated."""


class NotInplaceTranslatableError(DataStructureIOError):
    """Exception indicating that a type cannot be translated in-place.

    Use :meth:`~id_translation.dio.exceptions.NotInplaceTranslatableError.for_translatable` to build the
    standard message.

    Args:
        msg: The error message.
        translatable_type: Name of the type that cannot be translated in-place.
        hints: Hints to add as notes, after a link to the docs.
    """

    def __init__(self, msg: str, *, translatable_type: str | None = None, hints: str | _Iterable[str] = ()) -> None:
        super().__init__(msg, hints=hints)
        self.translatable_type = translatable_type

    @classmethod
    def for_translatable(cls, translatable: _Any, *, hints: str | _Iterable[str] = ()) -> _Self:
        """Create an error with the standard message."""
        translatable_type = type(translatable)
        return cls(
            f"Inplace translation not possible or implemented for type: {translatable_type}",
            translatable_type=f"{translatable_type.__module__}.{translatable_type.__qualname__}",
            hints=hints,
        )
