from collections import UserString
from typing import Callable, TypeVar
from uuid import UUID

from id_translation.types import IdType, IdTypes, Translatable


class UuidStr(UserString):
    def __init__(self, i: int) -> None:
        super().__init__(UUID(int=i))


IdFactory = Callable[[int], IdType]
IdFactories: list[IdFactory] = [float, int, str, UUID, UuidStr]
TranslatableT = TypeVar("TranslatableT", bound=Translatable[str, IdTypes])  # TODO Need Higher-Kinded TypeVars
