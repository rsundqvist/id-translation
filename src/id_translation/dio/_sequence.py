from collections.abc import Callable, Sequence
from typing import Any, TypeVar

import numpy as np
from rics.collections.misc import as_list

from ..offline import TranslationMap
from ..types import IdType, NameType, SourceType
from . import DataStructureIO
from .exceptions import NotInplaceTranslatableError

T = TypeVar("T", list, np.ndarray, tuple)  # type: ignore[type-arg]  # TODO: Higher-Kinded TypeVars


class SequenceIO(DataStructureIO[T, NameType, SourceType, IdType]):
    """Implementation for numpy arrays, Python lists and tuples."""

    @classmethod
    def handles_type(cls, arg: Any) -> bool:
        return isinstance(arg, (list, np.ndarray, tuple))

    @classmethod
    def extract(cls, translatable: T, names: list[NameType]) -> dict[NameType, Sequence[IdType]]:
        verify_names(len(translatable), names)
        return (
            {names[0]: as_list(translatable)}
            if len(names) == 1
            else {n: as_list(r) for n, r in zip(names, translatable)}
        )

    @classmethod
    def insert(
        cls,
        translatable: T,
        names: list[NameType],
        tmap: TranslationMap[NameType, SourceType, IdType],
        copy: bool,
    ) -> T | None:
        verify_names(len(translatable), names)
        t = translate_sequence(translatable, names, tmap)

        ctor: Callable[[list[str | None]], T]
        if copy:
            if isinstance(translatable, np.ndarray):
                ctor = np.array
            else:
                ctor = type(translatable)
            return ctor(t)

        try:
            translatable[:] = t[:]  # type: ignore
            return None
        except TypeError as e:
            raise NotInplaceTranslatableError(translatable) from e


def translate_sequence(s: T, names: list[NameType], tmap: TranslationMap[NameType, SourceType, IdType]) -> list[str]:
    """Return a translated copy of the sequence `s`."""
    if len(names) == 1:
        magic_dict = tmap[names[0]]
        return [magic_dict[i] for i in s]

    return [  # TODO resolve_io med cache
        translate_sequence(element, [name], tmap)  # type: ignore
        if SequenceIO.handles_type(element)
        else tmap[name][element]
        for name, element in zip(names, s)
    ]


def verify_names(data_len: int, names: list[NameType]) -> None:  # pragma: no cover
    """Verify that the length of names is either 1 or equal to the length of the data."""
    num_names = len(names)
    if num_names not in {1, data_len}:
        raise ValueError(
            f"Number of names {len(names)} must be 1 or equal to the length of the data ({data_len}) to "
            f"translate, but got {names=}."
        )
