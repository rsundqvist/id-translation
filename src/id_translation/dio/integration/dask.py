"""Integration for `Dask <https://www.dask.org/>`_ types."""

import typing as _t
from collections import abc as _abc

import pandas as _pd
from dask import compute as _compute
from dask import dataframe as _dd
from rics.misc import tname as _tname

from id_translation import types as _tt
from id_translation.dio import DataStructureIO as _DataStructureIO
from id_translation.dio.exceptions import NotInplaceTranslatableError as _NotInplaceTranslatableError
from id_translation.dio.integration.pandas import PandasIO as _PandasIO
from id_translation.offline import TranslationMap as _TranslationMap

DaskT = _t.TypeVar("DaskT", _dd.DataFrame, _dd.Series)
"""Supported ``dask`` types."""

PartitionT = _t.TypeVar("PartitionT", _pd.DataFrame, _pd.Series)
"""Supported ``dask`` partition types."""
PartitionIO = _PandasIO[PartitionT, str, _tt.SourceType, _tt.IdType]
"""A ``dask`` partition IO implementation."""

del _PandasIO  # Don't use by accident.


class DaskIO(_DataStructureIO[DaskT, str, _tt.SourceType, _tt.IdType]):
    """Optional IO implementation for ``dask`` types.

    Args:
        missing_as_nan: If set, unknown IDs will be `NaN`. Forwarded to :class:`.PandasIO`.
        as_category: Set `dtype='category'` in the result. Forwarded to :class:`.PandasIO`.

    Notes:
        Combining ``missing_as_nan=False`` with ``as_category=True`` can be unpredictable in distributed contexts.
    """

    priority = 1980

    def __init__(
        self,
        *,
        missing_as_nan: bool | None = None,
        as_category: bool = False,
    ) -> None:
        self._part_io = PartitionIO[_t.Any, _tt.SourceType, _tt.IdType](
            missing_as_nan=missing_as_nan,
            as_category=as_category,
        )

    @property
    def partition_io(self) -> PartitionIO[_t.Any, _tt.SourceType, _tt.IdType]:
        """The :class:`PartitionIO` implementation used by this instance."""
        return self._part_io

    @classmethod
    def handles_type(cls, arg: _t.Any) -> bool:
        return isinstance(arg, (_dd.DataFrame, _dd.Series))

    @classmethod
    def names(cls, translatable: DaskT) -> list[str] | None:
        if isinstance(translatable, _dd.DataFrame):
            return list(translatable.columns)

        return None if translatable.name is None else [translatable.name]

    @classmethod
    def extract(cls, translatable: DaskT, names: list[str]) -> dict[str, _abc.Sequence[_tt.IdType]]:
        if isinstance(translatable, _dd.Series):
            if len(names) != 1:
                msg = f"{len(names)=} != 1 is not supported for {_tname(translatable, include_module=True)}"
                raise NotImplementedError(msg)
            return {names[0]: translatable.unique().compute().to_list()}
        else:
            delayed = {n: translatable[n].unique() for n in names}
            name_to_ids = _compute(delayed)[0]
            return {name: ids.to_list() for name, ids in name_to_ids.items()}

    def insert(
        self,
        translatable: DaskT,
        names: list[str],
        tmap: _TranslationMap[str, _tt.SourceType, _tt.IdType],
        copy: bool,
    ) -> DaskT:
        if not copy:
            raise _NotInplaceTranslatableError(translatable)  # Can't in-place a compute graph.

        return translatable.map_partitions(  # type: ignore[no-any-return]
            translate_partition,
            names,
            tmap,
            self.partition_io,
        )


def translate_partition(
    part: PartitionT,
    names: list[str],
    tmap: _TranslationMap[str, _tt.SourceType, _tt.IdType],
    part_io: PartitionIO[PartitionT, _tt.SourceType, _tt.IdType],
) -> PartitionT:
    """Translate a single Dask partition."""
    if isinstance(part, _pd.DataFrame):
        part_io.insert(part, names, tmap, copy=False)
        return part
    else:
        return part_io.insert(part, names, tmap, copy=True)
