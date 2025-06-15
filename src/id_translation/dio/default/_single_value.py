from collections.abc import Sequence
from typing import Any
from uuid import UUID

from id_translation.offline import TranslationMap
from id_translation.types import IdType, NameType, SourceType

from .._data_structure_io import DataStructureIO
from ..exceptions import NotInplaceTranslatableError


class SingleValueIO(DataStructureIO[IdType, NameType, SourceType, IdType]):
    """IO implementation for ``int``, ``str`` and ``UUID`` types."""

    priority = 1500

    @classmethod
    def handles_type(cls, arg: Any) -> bool:
        return isinstance(arg, (int, str, UUID))

    @classmethod
    def extract(cls, translatable: IdType, names: list[NameType]) -> dict[NameType, Sequence[IdType]]:
        if len(names) != 1:  # pragma: no cover
            raise ValueError(f"Length of {names=} must be one.")

        return {names[0]: (translatable,)}

    @classmethod
    def insert(
        cls,
        translatable: IdType,
        names: list[NameType],
        tmap: TranslationMap[NameType, SourceType, IdType],
        copy: bool,
    ) -> str:
        if not copy:  # pragma: no cover
            raise NotInplaceTranslatableError(translatable)

        return tmap[names[0]][translatable]
