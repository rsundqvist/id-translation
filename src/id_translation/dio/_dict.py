from typing import Any, Dict, List, Optional, Sequence, TypeVar

from ..offline import TranslationMap
from ..types import IdType, NameType, SourceType
from ._data_structure_io import DataStructureIO

T = TypeVar("T", bound=Dict)  # type: ignore[type-arg]  # TODO: Higher-Kinded TypeVars


class DictIO(DataStructureIO):
    """Implementation for dicts."""

    @staticmethod
    def handles_type(arg: Any) -> bool:
        return isinstance(arg, dict)

    @staticmethod
    def extract(translatable: T, names: List[NameType]) -> Dict[NameType, Sequence[IdType]]:
        return {name: translatable[name] for name in names}

    @staticmethod
    def insert(
        translatable: T, names: List[NameType], tmap: TranslationMap[NameType, SourceType, IdType], copy: bool
    ) -> Optional[T]:
        translatable = dict(translatable) if copy else translatable  # type: ignore

        for name in filter(translatable.__contains__, names):
            translatable[name] = type(translatable[name])(map(tmap[name].get, translatable[name]))

        return translatable if copy else None
