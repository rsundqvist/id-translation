"""Insertion and extraction of IDs and translations."""
from abc import abstractmethod
from typing import Any, Dict, List, Optional, Sequence

from ..offline import TranslationMap
from ..types import IdType, NameType, SourceType


class DataStructureIO:
    """Insertion and extraction of IDs and translations."""

    @staticmethod
    def handles_type(arg: Any) -> bool:
        """Return ``True`` if the implementation handles data for the type of `arg`."""
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def extract(c: Any, names: List[NameType]) -> Dict[NameType, Sequence[IdType]]:
        """Extract IDs from `c`.

        Args:
            c: A collection to extract IDs from.
            names: List of names to extract IDs for.

        Returns:
            A dict ``{name, ids}``.
        """

    @staticmethod
    @abstractmethod
    def insert(
        c: Any, names: List[NameType], tmap: TranslationMap[NameType, SourceType, IdType], copy: bool
    ) -> Optional[Any]:
        """Insert translations into `c`.

        Args:
            c: A collection apply translations for. Modified iff ``copy=False``.
            names: Names in `t` to translate..
            tmap: Translations for IDs in `c`.
            copy: If ``True``, modify contents of the original collection `c`. Otherwise, return a copy.

        Returns:
            A copy of `c` if ``copy=True``. ``None`` otherwise.

        Raises:
            NotInplaceTranslatableError: If ``copy=False`` for a type which is not translatable in-place.
        """
