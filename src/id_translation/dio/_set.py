from collections.abc import Sequence
from typing import Any

from ..offline import TranslationMap
from ..types import IdType, NameType, SourceType
from ._data_structure_io import DataStructureIO


class SetIO(DataStructureIO[set[IdType], NameType, SourceType, IdType]):
    """Implementation for dicts."""

    @classmethod
    def handles_type(cls, arg: Any) -> bool:
        return isinstance(arg, set)

    @classmethod
    def extract(cls, translatable: set[IdType], names: list[NameType]) -> dict[NameType, Sequence[IdType]]:
        if len(names) != 1:  # pragma: no cover
            raise ValueError("Length of names must be one.")

        return {names[0]: list(translatable)}

    @classmethod
    def insert(
        cls,
        translatable: set[IdType],
        names: list[NameType],
        tmap: TranslationMap[NameType, SourceType, IdType],
        copy: bool,
    ) -> set[str] | None:
        magic_dict = tmap[names[0]]
        translated = {magic_dict[e] for e in translatable}

        if copy:
            return translated

        translatable.clear()
        translatable.update(translated)  # type: ignore[arg-type]
        return None
