from typing import Any, Dict, List, Optional, Sequence, Union

from rics.collections.misc import as_list

from ..offline import TranslationMap
from ..types import IdType, NameType, SourceType
from ._data_structure_io import DataStructureIO


class DictIO(DataStructureIO):
    """Implementation for dicts."""

    # TODO types here all mostly wrong. Would require a lot of overloads to fix..

    @staticmethod
    def handles_type(arg: Any) -> bool:
        return isinstance(arg, dict)

    @staticmethod
    def names(translatable: Dict[NameType, IdType]) -> List[NameType]:
        return list(translatable)

    @staticmethod
    def extract(translatable: Dict[NameType, IdType], names: List[NameType]) -> Dict[NameType, Sequence[IdType]]:
        return {name: as_list(translatable[name]) for name in names}

    @staticmethod
    def insert(
        translatable: Union[Dict[NameType, IdType], Dict[NameType, Sequence[IdType]]],
        names: List[NameType],
        tmap: TranslationMap[NameType, SourceType, IdType],
        copy: bool,
    ) -> Optional[Dict[NameType, Any]]:
        from ._resolve import resolve_io

        translated = {
            key: resolve_io(value).insert(value, [key], tmap, copy=True) if key in names else value
            for key, value in translatable.items()
        }

        if copy:
            return translated

        translatable.clear()
        translatable.update(translated)  # type: ignore[arg-type]
        return None
