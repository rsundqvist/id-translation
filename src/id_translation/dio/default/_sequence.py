import os
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, TypeVar

from rics.collections.misc import as_list

from id_translation.offline import TranslationMap
from id_translation.types import IdType, NameType, SourceType

from .._data_structure_io import DataStructureIO
from ..exceptions import NotInplaceTranslatableError

try:
    from numpy import array, ndarray
except ImportError:

    class ndarray:  # type: ignore  # noqa
        """Dummy implementation; numpy is not available."""

    array = ndarray  # type: ignore[assignment]

SequenceT = TypeVar("SequenceT", list, ndarray, tuple)  # type: ignore[type-arg]  # TODO: Higher-Kinded TypeVars


class SequenceIO(DataStructureIO[SequenceT, NameType, SourceType, IdType]):
    """IO implementation for ``list``, ``tuple`` and  ``numpy.array`` types."""

    priority = 1100

    if not TYPE_CHECKING and os.environ.get("SPHINX_BUILD") == "true":
        SequenceT = SequenceT  # type: ignore[attr-defined]
        """Generic sequence type.

        This property does not exist at runtime. The element type cannot be parameterized due to limitations in the
        ``TypeVar`` implementation.
        """

    @classmethod
    def handles_type(cls, arg: Any) -> bool:
        return isinstance(arg, (list, ndarray, tuple))

    @classmethod
    def extract(cls, translatable: SequenceT, names: list[NameType]) -> dict[NameType, Sequence[IdType]]:
        verify_names(len(translatable), names)
        return (
            {names[0]: as_list(translatable)}
            if len(names) == 1
            else {n: as_list(r) for n, r in zip(names, translatable, strict=True)}
        )

    @classmethod
    def insert(
        cls,
        translatable: SequenceT,
        names: list[NameType],
        tmap: TranslationMap[NameType, SourceType, IdType],
        copy: bool,
    ) -> SequenceT | None:
        verify_names(len(translatable), names)
        t = translate_sequence(translatable, names, tmap)

        ctor: Callable[[list[str | None]], SequenceT]
        if copy:
            if isinstance(translatable, ndarray):
                ctor = array
            else:
                ctor = type(translatable)
            return ctor(t)

        try:
            translatable[:] = t[:]  # type: ignore
            return None
        except TypeError as e:
            raise NotInplaceTranslatableError(translatable) from e


def translate_sequence(
    s: SequenceT, names: list[NameType], tmap: TranslationMap[NameType, SourceType, IdType]
) -> list[str]:
    """Return a translated copy of the sequence `s`."""
    if len(names) == 1:
        magic_dict = tmap[names[0]]
        return [magic_dict[i] for i in s]

    return [  # TODO resolve_io med cache
        translate_sequence(element, [name], tmap)  # type: ignore
        if SequenceIO.handles_type(element)
        else tmap[name][element]
        for name, element in zip(names, s, strict=True)
    ]


def verify_names(data_len: int, names: list[NameType]) -> None:  # pragma: no cover
    """Verify that the length of names is either 1 or equal to the length of the data."""
    num_names = len(names)
    if num_names not in {1, data_len}:
        raise ValueError(
            f"Number of names {len(names)} must be 1 or equal to the length of the data ({data_len}) to "
            f"translate, but got {names=}."
        )
