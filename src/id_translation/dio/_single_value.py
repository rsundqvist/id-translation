from typing import Any, Dict, List, Sequence
from uuid import UUID

from ..offline import TranslationMap
from ..types import IdType, NameType, SourceType
from . import DataStructureIO
from .exceptions import NotInplaceTranslatableError


class SingleValueIO(DataStructureIO):
    """Implementation for non-iterables. And strings."""

    @staticmethod
    def handles_type(arg: Any) -> bool:
        return isinstance(arg, (int, str, UUID))

    @staticmethod
    def extract(translatable: IdType, names: List[NameType]) -> Dict[NameType, Sequence[IdType]]:
        if len(names) != 1:  # pragma: no cover
            raise ValueError("Length of names must be one.")

        return {names[0]: (translatable,)}

    @staticmethod
    def insert(
        translatable: IdType, names: List[NameType], tmap: TranslationMap[NameType, SourceType, IdType], copy: bool
    ) -> str:
        if not copy:  # pragma: no cover
            raise NotInplaceTranslatableError(translatable)

        return tmap[names[0]][translatable]
