"""Integration for `Dask <https://www.dask.org/>`_ types."""

import typing as _t

from dask import compute as _compute
from dask import dataframe as dd

from id_translation import dio as _dio
from id_translation import types as _tt
from id_translation.offline import MagicDict as _MagicDict
from id_translation.offline import TranslationMap as _TranslationMap

DaskT = _t.TypeVar("DaskT", dd.DataFrame, dd.Series)
"""Supported ``dask`` types."""


class DaskIO(_dio.DataStructureIO[DaskT, str, _tt.SourceType, _tt.IdType]):
    """IO implementation for ``dask`` types."""

    @classmethod
    def handles_type(cls, arg: _t.Any) -> bool:
        return isinstance(arg, (dd.DataFrame, dd.Series))

    @classmethod
    def names(cls, translatable: DaskT) -> list[str] | None:
        if isinstance(translatable, dd.DataFrame):
            return list(translatable.columns)

        return None if translatable.name is None else [translatable.name]

    @classmethod
    def extract(cls, translatable: DaskT, names: list[str]) -> dict[str, _t.Sequence[_tt.IdType]]:
        if isinstance(translatable, dd.Series):
            if len(names) != 1:
                raise RuntimeError(f"{len(names)=} != 1 is not supported for dask.Series")
            return {names[0]: translatable.unique().compute().to_list()}
        else:
            delayed = {n: translatable[n].unique() for n in names}
            name_to_ids = _compute(delayed)[0]
            return {name: ids.to_list() for name, ids in name_to_ids.items()}

    @classmethod
    def insert(
        cls,
        translatable: DaskT,
        names: list[str],
        tmap: _TranslationMap[str, _tt.SourceType, _tt.IdType],
        copy: bool,
    ) -> DaskT | None:
        if not copy:
            from id_translation.dio.exceptions import NotInplaceTranslatableError

            raise NotInplaceTranslatableError(translatable)  # Can't in-place a compute graph.

        if isinstance(translatable, dd.Series):
            return _translate_series(translatable, tmap[names[0]])
        else:
            return _translate_frame(translatable, names, tmap)


def _translate_series(series: dd.Series, magic_dict: _MagicDict[_tt.IdType]) -> dd.Series:
    mapping = {idx: magic_dict[idx] for idx in series.unique().compute()}
    return series.replace(mapping)  # type: ignore[no-any-return]


def _translate_frame(
    df: dd.DataFrame,
    names: list[_tt.NameType],
    tmap: _TranslationMap[_tt.NameType, _tt.SourceType, _tt.IdType],
) -> dd.DataFrame:
    original_columns = df.columns

    try:
        df.columns = [str(i) for i in range(len(original_columns))]
        for name, int_col in zip(original_columns, df.columns, strict=True):
            if name in names:
                translated = _translate_series(df[int_col], tmap[name])
                df[int_col] = translated
    finally:
        df.columns = original_columns

    return df
