from collections.abc import Sequence
from typing import Any

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
    def names(translatable: dict[NameType, IdType]) -> list[NameType]:
        return list(translatable)

    @staticmethod
    def extract(translatable: dict[NameType, IdType], names: list[NameType]) -> dict[NameType, Sequence[IdType]]:
        return {name: as_list(translatable[name]) for name in names}

    @staticmethod
    def insert(
        translatable: dict[NameType, IdType] | dict[NameType, Sequence[IdType]],
        names: list[NameType],
        tmap: TranslationMap[NameType, SourceType, IdType],
        copy: bool,
    ) -> dict[NameType, Any] | None:
        from rics.logs import disable_temporarily

        from ._resolve import LOGGER as RESOLVE_IO_LOGGER
        from ._resolve import resolve_io

        with disable_temporarily(RESOLVE_IO_LOGGER):
            translated = {
                key: resolve_io(value).insert(value, [key], tmap, copy=True) if key in names else value
                for key, value in translatable.items()
            }

        if copy:
            return translated

        translatable.clear()
        translatable.update(translated)  # type: ignore[arg-type]
        return None
