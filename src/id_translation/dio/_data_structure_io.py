"""Insertion and extraction of IDs and translations."""

from abc import abstractmethod
from collections.abc import Sequence
from typing import Any, Generic

from ..offline import TranslationMap
from ..types import IdType, NameType, SourceType, TranslatableT


class DataStructureIO(Generic[TranslatableT, NameType, SourceType, IdType]):
    """Insertion and extraction of IDs and translations."""

    @classmethod
    def register(cls) -> None:
        """Register this implementation for all :class:`.Translator` instances.

        See :func:`.dio.register_io` for details.
        """
        from ._resolve import register_io

        return register_io(cls)

    @classmethod
    def get_rank(cls) -> int:
        """Return the rank of this implementation.

        See :func:`.dio.get_resolution_order` for details.

        Returns:
            Implementation rank.

        Raises:
            ValueError: If the implementation is not registered.
        """
        from ._resolve import get_resolution_order

        try:
            return get_resolution_order(real=True).index(cls)
        except ValueError:
            raise ValueError(f"not registered: {cls.__name__}") from None

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
            NotInplaceTranslatableError: If ``copy=False`` for a type which is not translatable in-place.
        """
