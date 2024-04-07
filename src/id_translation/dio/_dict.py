from collections.abc import Sequence
from typing import Any

from rics.collections.misc import as_list

from ..offline import TranslationMap
from ..types import IdType, NameType, SourceType
from ._data_structure_io import DataStructureIO


class DictIO(DataStructureIO[dict[NameType, IdType], NameType, SourceType, IdType]):
    """Implementation for dicts."""

    @classmethod
    def handles_type(cls, arg: Any) -> bool:
        return isinstance(arg, dict)

    @classmethod
    def names(cls, translatable: dict[NameType, IdType]) -> list[NameType]:
        return list(translatable)

    @classmethod
    def extract(cls, translatable: dict[NameType, IdType], names: list[NameType]) -> dict[NameType, Sequence[IdType]]:
        return {name: as_list(translatable[name]) for name in names}

    @classmethod
    def insert(
        cls,
        translatable: dict[NameType, IdType] | dict[NameType, Sequence[IdType]],
        names: list[NameType],
        tmap: TranslationMap[NameType, SourceType, IdType],
        copy: bool,
    ) -> dict[NameType, Any] | None:
        from rics.logs import disable_temporarily

        from ._resolve import LOGGER as RESOLVE_IO_LOGGER
        from ._resolve import resolve_io

        with disable_temporarily(RESOLVE_IO_LOGGER):
            translated = {}
            for key, value in translatable.items():
                dio: DataStructureIO[IdType | Sequence[IdType], NameType, SourceType, IdType] = resolve_io(value)
                if key in names:
                    translated[key] = dio.insert(value, [key], tmap, copy=True)
                else:
                    translated[key] = value

        if copy:
            return translated

        translatable.clear()
        translatable.update(translated)  # type: ignore[arg-type]
        return None
