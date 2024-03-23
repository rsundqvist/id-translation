"""Insertion and extraction of IDs and translations."""

from abc import abstractmethod
from collections.abc import Sequence
from typing import Any

from ..offline import TranslationMap
from ..types import IdType, NameType, SourceType


class DataStructureIO:
    """Insertion and extraction of IDs and translations."""

    @staticmethod
    @abstractmethod
    def handles_type(arg: Any) -> bool:
        """Return ``True`` if the implementation handles data for the type of `arg`."""

    @staticmethod
    def names(translatable: Any) -> list[NameType] | None:
        """Extract names from `translatable`.

        Args:
            translatable: Data to extract names from.

        Returns:
            A list of names to translate. Returns ``None`` if names cannot be extracted.
        """
        return translatable.name if hasattr(translatable, "name") else None

    @staticmethod
    @abstractmethod
    def extract(translatable: Any, names: list[NameType]) -> dict[NameType, Sequence[IdType]]:
        """Extract IDs from `translatable`.

        Args:
            translatable: Data to extract IDs from.
            names: List of names in `translatable` to extract IDs for.

        Returns:
            A dict ``{name: ids}``.
        """

    @staticmethod
    @abstractmethod
    def insert(
        translatable: Any, names: list[NameType], tmap: TranslationMap[NameType, SourceType, IdType], copy: bool
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
