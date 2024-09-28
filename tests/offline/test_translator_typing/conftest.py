from typing import TypeAlias
from uuid import UUID

from id_translation import Translator as _Base

GBG_ID = UUID(fields=(1632, 0, 0, 0, 0, 0))
STO_ID = UUID(fields=(1266, 0, 0, 0, 0, 0))

PLACES: dict[UUID, str] = {GBG_ID: "Göteborg", STO_ID: "Stockholm"}
PEOPLE: dict[int, str] = {1999: "Sofia", 1991: "Richard"}


class TypedTranslator(_Base[str, bool, int | UUID]):
    def __init__(self) -> None:
        from id_translation.fetching import MemoryFetcher
        from id_translation.mapping import Mapper
        from id_translation.offline.types import PlaceholderTranslations

        data = {
            True: PlaceholderTranslations.make(True, PEOPLE),
            False: PlaceholderTranslations.make(False, PLACES),
        }
        fetcher: MemoryFetcher[bool, int | UUID] = MemoryFetcher(data, return_all=False)

        is_human: dict[str, bool] = {"places": False, "people": True}
        mapper: Mapper[str, bool, None] = Mapper(overrides=is_human)

        super().__init__(fetcher=fetcher, fmt="{id!s:.8}:{name}", mapper=mapper)


UnionDict: TypeAlias = dict[str, list[UUID | int]]


def make_translatable() -> UnionDict:
    return {"people": list(PEOPLE), "places": list(PLACES)}
