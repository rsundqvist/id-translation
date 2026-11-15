import os
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
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
    def names(cls, translatable: SequenceT) -> None:  # noqa: ARG003
        return None

    @classmethod
    def extract(cls, translatable: SequenceT, names: list[NameType]) -> Mapping[NameType, Sequence[IdType]]:
        verify_names(len(translatable), names)
        if len(names) == 1:
            return {names[0]: as_list(translatable)}

        ids: dict[NameType, list[IdType]] = {}
        for n, r in zip(names, translatable, strict=True):
            ids.setdefault(n, []).extend(as_list(r))  # Names may be repeated.
        return ids

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

        hint = (
            "Use copy=True, or an array with dtype=object." if isinstance(translatable, ndarray) else "Use copy=True."
        )
        if isinstance(translatable, ndarray) and translatable.dtype.kind not in "OUST":
            # Numpy casts strings into other dtypes where it can, e.g. any non-empty string to True.
            raise NotInplaceTranslatableError.for_translatable(translatable, hints=hint)
        if isinstance(translatable, ndarray) and translatable.dtype.kind in "US":
            # Numpy truncates strings that are wider than the dtype without raising.
            width = translatable.dtype.itemsize // (4 if translatable.dtype.kind == "U" else 1)
            if any(n > width for n in _widths(t)):
                raise NotInplaceTranslatableError.for_translatable(translatable, hints=hint)

        try:
            translatable[:] = t[:]  # type: ignore
            return None
        except (TypeError, ValueError) as e:  # ValueError: e.g. non-ASCII translations for a bytes array.
            raise NotInplaceTranslatableError.for_translatable(translatable, hints=hint) from e


def _widths(translations: Iterable[Any]) -> Iterator[int]:
    for translation in translations:
        if isinstance(translation, list):
            yield from _widths(translation)
        else:
            yield len(str(translation))


def translate_sequence(
    s: SequenceT,
    names: list[NameType],
    tmap: TranslationMap[NameType, SourceType, IdType],
) -> list[str]:
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
