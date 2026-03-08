"""Integration for `Arrow <https://arrow.apache.org/>`_ types."""

import typing as _t
from collections import abc as _abc

import pyarrow as _pa  #  type: ignore[import-untyped]
from rics.misc import tname as _tname

from id_translation import dio as _dio
from id_translation import types as _tt
from id_translation.dio.exceptions import NotInplaceTranslatableError as _NotInplaceTranslatableError
from id_translation.offline import MagicDict as _MagicDict
from id_translation.offline import TranslationMap as _TranslationMap

ArrowT = _t.TypeVar("ArrowT", _pa.Table, _pa.Array, _pa.ChunkedArray)
"""Supported ``arrow`` types."""
_ArrayT = _t.TypeVar("_ArrayT", _pa.Array, _pa.ChunkedArray)


class ArrowIO(_dio.DataStructureIO[ArrowT, str, _tt.SourceType, _tt.IdType]):
    """Optional IO implementation for ``pyarrow`` types.

    Args:
        missing_as_nan: If set, unknown IDs will be ``null``. If ``False``, placeholders such as ``'<Failed: id=-1>'``
            will be used instead.
    """

    def __init__(
        self,
        *,
        missing_as_nan: bool = False,
    ) -> None:
        self._missing_as_nan = missing_as_nan

    priority = -1900

    @classmethod
    def handles_type(cls, arg: _t.Any) -> bool:
        return isinstance(arg, (_pa.Table, _pa.Array, _pa.ChunkedArray))

    @classmethod
    def names(cls, translatable: ArrowT) -> list[str] | None:
        if isinstance(translatable, _pa.Table):
            return translatable.column_names  # type: ignore[no-any-return]

        name = getattr(translatable, "_name", None)
        return [name] if name else None

    @classmethod
    def _is_record_batch_list(cls, translatable: ArrowT) -> _t.TypeGuard[list[_pa.RecordBatch]]:
        return isinstance(translatable, list) and len(translatable) > 0 and isinstance(translatable[0], _pa.RecordBatch)

    @classmethod
    def extract(cls, translatable: ArrowT, names: list[str]) -> dict[str, _abc.Sequence[_tt.IdType]]:
        if isinstance(translatable, _pa.Table):
            return {name: cls._extract_unique(translatable.column(name)) for name in names}
        else:
            if len(names) != 1:
                msg = f"{len(names)=} != 1 is not supported for {_tname(translatable, include_module=True)}"
                raise NotImplementedError(msg)
            return {names[0]: cls._extract_unique(translatable)}

    def insert(
        self,
        translatable: ArrowT,
        names: list[str],
        tmap: _TranslationMap[str, _tt.SourceType, _tt.IdType],
        copy: bool,
    ) -> ArrowT:
        if not copy:
            raise _NotInplaceTranslatableError(translatable)

        if isinstance(translatable, _pa.Table):
            for name in names:
                translated_ids = self._translate_array(translatable.column(name), tmap[name])
                translatable = translatable.set_column(translatable.column_names.index(name), name, translated_ids)
        else:
            if len(names) != 1:
                msg = f"{len(names)=} != 1 is not supported for {_tname(translatable, include_module=True)}"
                raise NotImplementedError(msg)
            translatable = self._translate_array(translatable, tmap[names[0]])

        return translatable

    @classmethod
    def _extract_unique(cls, ids: _ArrayT) -> list[_tt.IdType]:
        return ids.unique().to_pylist()  # type: ignore[no-any-return]

    def _translate_array(self, ids: _ArrayT, magic_dict: _MagicDict[_tt.IdType]) -> _ArrayT:
        get_item = magic_dict.real_get if self._missing_as_nan else magic_dict.__getitem__
        translations = {idx: get_item(idx) for idx in self._extract_unique(ids)}

        index = _pa.compute.index_in(ids, _pa.array(translations))
        return _pa.compute.take(_pa.array(translations.values()), index)
