"""Data structure IO exceptions."""

from collections.abc import Iterable as _Iterable
from typing import Any as _Any
from typing import ClassVar as _ClassVar
from typing import Self as _Self

from .._utils import add_hints as _add_hints
from .._utils import type_name as _type_name


class DataStructureIOError(TypeError):
    """Base class for IO exceptions.

    Args:
        msg: The error message.
        hints: Hints to add as notes, after a link to the docs.
    """

    _anchor: _ClassVar[str] = "user-defined-integrations"  # The translation-io section that the first hint links to.

    def __init__(self, msg: str, *, hints: str | _Iterable[str] = ()) -> None:
        super().__init__(msg)

        from id_translation._utils import DOC_LINK  # noqa: PLC0415

        url = DOC_LINK + f"documentation/translation-io.html#{self._anchor}"
        self.add_note(f"Hint: {url}")

        _add_hints(self, hints)


class UntranslatableTypeError(DataStructureIOError):
    """Exception indicating that a type cannot be translated.

    Use :meth:`~id_translation.dio.exceptions.UntranslatableTypeError.for_translatable` to build the standard message.

    Args:
        msg: The error message.
        translatable_type: Name of the type that cannot be translated.
        hints: Hints to add as notes, after a link to the docs.
    """

    def __init__(self, msg: str, *, translatable_type: str | None = None, hints: str | _Iterable[str] = ()) -> None:
        super().__init__(msg, hints=hints)
        self.translatable_type = translatable_type

    @classmethod
    def for_translatable(cls, translatable: _Any, *, hints: str | _Iterable[str] = ()) -> _Self:
        """Create an error with the standard message."""
        return cls(
            f"Type {type(translatable)} cannot be translated.",
            translatable_type=_type_name(translatable),
            hints=hints,
        )


class NotInplaceTranslatableError(DataStructureIOError):
    """Exception indicating that a type cannot be translated in-place.

    Use :meth:`~id_translation.dio.exceptions.NotInplaceTranslatableError.for_translatable` to build the
    standard message.

    Args:
        msg: The error message.
        translatable_type: Name of the type that cannot be translated in place.
        hints: Hints to add as notes, after a link to the docs.
    """

    def __init__(self, msg: str, *, translatable_type: str | None = None, hints: str | _Iterable[str] = ()) -> None:
        super().__init__(msg, hints=hints)
        self.translatable_type = translatable_type

    @classmethod
    def for_translatable(cls, translatable: _Any, *, hints: str | _Iterable[str] = ()) -> _Self:
        """Create an error with the standard message."""
        return cls(
            f"Inplace translation not possible or implemented for type: {type(translatable)}",
            translatable_type=_type_name(translatable),
            hints=hints,
        )


class RegistryReentryError(DataStructureIOError):
    """The IO registry was used while it was loading the ``id_translation.dio`` entrypoint integrations.

    Typically raised when a module loaded as an entrypoint calls :meth:`~id_translation.dio.DataStructureIO.register`
    at import time. Not an ``ImportError``, so that optional-import guards in the entrypoint module do not swallow it.
    """

    _anchor = "automatic-integration-discovery"
