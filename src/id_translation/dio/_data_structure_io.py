"""Insertion and extraction of IDs and translations."""

from abc import abstractmethod
from collections.abc import Sequence
from typing import Any, ClassVar, Generic

from ..offline import TranslationMap
from ..types import IdType, NameType, SourceType, TranslatableT
from ._util import pretty_io_name
from .exceptions import DataStructureIOError


class DataStructureIO(Generic[TranslatableT, NameType, SourceType, IdType]):
    """Insertion and extraction of IDs and translations."""

    # Priority changes are caught only when the registry is read (see `_verify_priorities`). The error then surfaces
    # far from the assignment, and assigning while other threads translate makes them raise. A metaclass `__setattr__`
    # would catch the assignment itself, but every subclass inherits the metaclass, so a downstream implementation that
    # also derives from a base with an unrelated metaclass of its own fails at class creation with a metaclass conflict.
    priority: ClassVar[int] = 10_000
    """Determines the order in which implementations are considered, largest ``abs(priority)`` first.

    A negative value makes the implementation opt-in. To change the value, assign it and then call ``register()``. See
    the :ref:`priority rules <io-priority>` for details.
    """

    @classmethod
    def register(cls) -> None:
        """Enable this implementation for all :class:`~id_translation.Translator` instances.

        See :func:`dio.register_io <id_translation.dio.register_io>` for details.
        """
        from ._resolve import register_io  # noqa: PLC0415

        return register_io(cls)

    @classmethod
    def unregister(cls) -> None:
        """Disable this implementation for all :class:`~id_translation.Translator` instances.

        See :func:`dio.unregister_io <id_translation.dio.unregister_io>` for details.
        """
        from ._resolve import unregister_io  # noqa: PLC0415

        return unregister_io(cls)

    @classmethod
    def is_registered(cls) -> bool:
        """Returns registration status for this implementation.

        See :func:`dio.is_registered <id_translation.dio.is_registered>` for details.
        """
        from ._resolve import is_registered  # noqa: PLC0415

        return is_registered(cls)

    @classmethod
    def get_rank(cls) -> int:
        """Return the rank of this implementation.

        See :func:`dio.get_resolution_order <id_translation.dio.get_resolution_order>` for details. The highest possible
        rank is 0.

        Returns:
            Implementation rank.

        Raises:
            ~id_translation.dio.exceptions.DataStructureIOError: If the implementation is not registered, or if a
                `priority` change awaits ``register()`` or ``unregister()`` (see :ref:`priority rules <io-priority>`).
        """
        from ._resolve import get_resolution_order  # noqa: PLC0415

        try:
            return get_resolution_order().index(cls)
        except ValueError:
            exc = DataStructureIOError(f"Not registered: {cls.__name__}")
            exc.add_note(f"Hint: Use {pretty_io_name(cls)}.register() to register this implementation.")
            raise exc from None

    @classmethod
    @abstractmethod
    def handles_type(cls, arg: Any) -> bool:
        """Return ``True`` if the implementation handles data for the type of `arg`."""

    def names(self, translatable: TranslatableT) -> list[NameType] | None:
        """Extract names from `translatable`.

        Args:
            translatable: Data to extract names from.

        Returns:
            A list of names to translate. Returns ``None`` if names cannot be extracted.
        """
        return translatable.name if hasattr(translatable, "name") else None

    @abstractmethod
    def extract(self, translatable: TranslatableT, names: list[NameType]) -> dict[NameType, Sequence[IdType]]:
        """Extract IDs from `translatable`.

        Args:
            translatable: Data to extract IDs from.
            names: List of names in `translatable` to extract IDs for.

        Returns:
            A dict ``{name: ids}``.
        """

    @abstractmethod
    def insert(
        self,
        translatable: TranslatableT,  # TODO Higher-Kinded TypeVars
        names: list[NameType],
        tmap: TranslationMap[NameType, SourceType, IdType],
        copy: bool,
    ) -> Any | None:
        """Insert translations into `translatable`.

        Args:
            translatable: Data to translate. Modified iff ``copy=False``.
            names: Names in `translatable` to translate.
            tmap: Translations for IDs in `translatable`.
            copy: If ``True``, modify contents of the original `translatable`. Otherwise, returns a copy.

        Returns:
            A copy of `translatable` if ``copy=True``, ``None`` otherwise.

        Raises:
            ~id_translation.dio.exceptions.NotInplaceTranslatableError: If ``copy=False`` for a type which is not
                translatable in-place.
        """
