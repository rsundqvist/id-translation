import os
import warnings
from collections import defaultdict
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, TypeVar

import pandas as pd
from pandas.api.types import is_float_dtype, is_numeric_dtype

from id_translation.offline import TranslationMap
from id_translation.types import IdType, NameType, SourceType

from .._data_structure_io import DataStructureIO
from ..exceptions import NotInplaceTranslatableError
from ._sequence import SequenceIO, translate_sequence, verify_names

PandasT = TypeVar("PandasT", pd.DataFrame, pd.Series, pd.Index, pd.MultiIndex)
PandasVectorT = TypeVar("PandasVectorT", pd.Series, pd.Index)


class PandasIO(DataStructureIO[PandasT, NameType, SourceType, IdType]):
    """IO implementation for ``pandas`` types."""

    priority = 1999

    if not TYPE_CHECKING and os.environ.get("SPHINX_BUILD") == "true":
        PandasT = PandasT  # type: ignore
        """Generic pandas type.

        This property does not exist at runtime.
        """

    @classmethod
    def handles_type(cls, arg: Any) -> bool:
        return isinstance(arg, (pd.DataFrame, pd.Series, pd.Index))

    @classmethod
    def names(cls, translatable: PandasT) -> list[NameType] | None:
        if isinstance(translatable, pd.DataFrame):
            columns = translatable.columns
            if isinstance(columns, pd.MultiIndex):
                return list(columns.get_level_values(-1))
            else:
                return list(columns)

        if isinstance(translatable, pd.MultiIndex):
            names = [n for n in translatable.names if n is not None]
            return names or None

        return None if translatable.name is None else [translatable.name]

    @classmethod
    def extract(cls, translatable: PandasT, names: list[NameType]) -> dict[NameType, Sequence[IdType]]:
        if isinstance(translatable, pd.DataFrame):
            ans = defaultdict(list)
            for i, name in enumerate(translatable.columns):
                if name in names:
                    ans[name].extend(_float_to_int(translatable.iloc[:, i]))
            return dict(ans)
        elif isinstance(translatable, pd.MultiIndex):
            # This will error on duplicate names, which is probably a good thing.
            return {name: list(translatable.unique(name)) for name in names}
        elif isinstance(translatable, (pd.Series, pd.Index)):
            verify_names(len(translatable), names)
            translatable = _float_to_int(translatable)
            if len(names) == 1:
                return {names[0]: translatable.unique().tolist()}
            else:
                return SequenceIO.extract(translatable, names)

        raise TypeError(f"This should not happen: {type(translatable)=}")  # pragma: no cover

    @classmethod
    def insert(
        cls,
        translatable: PandasT,
        names: list[NameType],
        tmap: TranslationMap[NameType, SourceType, IdType],
        copy: bool,
    ) -> PandasT | None:
        if not copy:
            if isinstance(translatable, pd.DataFrame):
                pass  # Ok
            elif isinstance(translatable, pd.Series):
                pass  # Ok, for now.   # TODO(issues/170): PDEP-6 check
            else:
                raise NotInplaceTranslatableError(translatable)

        if isinstance(translatable, pd.Index):
            return _translate_index(translatable, names, tmap)

        if isinstance(translatable, pd.DataFrame):
            return _translate_frame(translatable, names, tmap, copy)

        if isinstance(translatable, pd.Series):
            return _translate_series(translatable, names, tmap, copy)

        raise TypeError(f"This should not happen: {type(translatable)=}")  # pragma: no cover


def _translate_pandas_vector(
    pvt: PandasVectorT,
    names: list[NameType],
    tmap: TranslationMap[NameType, SourceType, IdType],
) -> list[str | None] | PandasVectorT:
    verify_names(len(pvt), names)

    if len(names) == 1:
        # Optimization for single-name vectors. Faster than SequenceIO for pretty much every size.
        magic_dict = tmap[names[0]]

        mapping: dict[IdType, str | None]
        if is_numeric_dtype(pvt):
            # We don't need to cast float to int here, since hash(1.0) == hash(1). The cast in extract() is required
            # because some database drivers may complain, especially if they receive floats (especially NaN).
            mapping = {idx: magic_dict[idx] for idx in pvt.unique()}
            return pvt.map(mapping)
        else:
            mapping = {}
            data: list[Any] = pvt.to_list()
            for i, idx in enumerate(data):
                if idx in mapping:
                    value = mapping[idx]
                else:
                    value = magic_dict[idx]
                    mapping[idx] = value
                data[i] = value

        return data
    else:
        return translate_sequence(pvt, names, tmap)


def _translate_index(
    index: PandasT,
    names: list[NameType],
    tmap: TranslationMap[NameType, SourceType, IdType],
) -> PandasT | None:
    if isinstance(index, pd.MultiIndex):
        df = index.to_frame()
        _translate_frame(df, names, tmap, copy=False)
        return pd.MultiIndex.from_frame(df, names=index.names)

    result = _translate_pandas_vector(index, names, tmap)
    if isinstance(result, pd.Index):
        return result
    return pd.Index(result, name=index.name, copy=False)


def _translate_frame(
    df: pd.DataFrame,
    names: list[NameType],
    tmap: TranslationMap[NameType, SourceType, IdType],
    copy: bool,
) -> pd.DataFrame:
    if copy:
        df = df.copy()

    original_columns = df.columns

    try:
        df.columns = pd.RangeIndex(len(original_columns))
        for name, int_col in zip(original_columns, df.columns, strict=True):
            if name in names:
                translated = _translate_pandas_vector(df[int_col], [name], tmap)
                df[int_col] = translated
    finally:
        df.columns = original_columns

    return df if copy else None


def _translate_series(
    series: pd.Series,
    names: list[NameType],
    tmap: TranslationMap[NameType, SourceType, IdType],
    copy: bool,
) -> pd.Series | None:
    result = _translate_pandas_vector(series, names, tmap)
    if copy:
        if isinstance(result, pd.Series):
            return result
        return pd.Series(result, index=series.index, name=series.name, copy=False)
    with warnings.catch_warnings():
        warnings.simplefilter(action="ignore", category=FutureWarning)  # TODO(issues/170): PDEP-6 check
        series[:] = result
    return None


def _float_to_int(pvt: PandasVectorT) -> PandasVectorT:
    return pvt.dropna().astype(int) if is_float_dtype(pvt) else pvt
