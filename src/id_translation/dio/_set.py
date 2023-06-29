from typing import Any, Dict, List, Optional, Sequence, Set

from ..offline import TranslationMap
from ..types import IdType, NameType, SourceType
from ._data_structure_io import DataStructureIO


class SetIO(DataStructureIO):
    """Implementation for dicts."""

    @staticmethod
    def handles_type(arg: Any) -> bool:
        return isinstance(arg, set)

    @staticmethod
    def extract(translatable: Set[IdType], names: List[NameType]) -> Dict[NameType, Sequence[IdType]]:
        if len(names) != 1:  # pragma: no cover
            raise ValueError("Length of names must be one.")

        return {names[0]: list(translatable)}

    @staticmethod
    def insert(
        translatable: Set[IdType], names: List[NameType], tmap: TranslationMap[NameType, SourceType, IdType], copy: bool
    ) -> Optional[Set[Optional[str]]]:
        magic_dict = tmap[names[0]]
        translated = {magic_dict.get(e) for e in translatable}

        if copy:
            return translated

        translatable.clear()
        translatable.update(translated)  # type: ignore[arg-type]
        return None
