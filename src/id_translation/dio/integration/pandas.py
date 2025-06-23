"""Integration for `Pandas <https://pandas.pydata.org/>`_ types."""

import typing as _t
import warnings as _warnings
from collections import abc as _abc
from collections import defaultdict as _defaultdict

import pandas as _pd

from id_translation import dio as _dio
from id_translation import types as _tt
from id_translation.dio.default import _sequence
from id_translation.dio.exceptions import NotInplaceTranslatableError as _NotInplaceTranslatableError
from id_translation.offline import TranslationMap as _TranslationMap

PandasT = _t.TypeVar("PandasT", _pd.DataFrame, _pd.Series, _pd.Index, _pd.MultiIndex)
"""Supported ``pandas`` types."""
_VectorT = _t.TypeVar("_VectorT", _pd.Series, _pd.Index)
"""Types with ``ndim==1``."""


class PandasIO(_dio.DataStructureIO[PandasT, _tt.NameType, _tt.SourceType, _tt.IdType]):
    """Optional IO implementation for ``pandas`` types."""

    priority = 1999

    @classmethod
    def handles_type(cls, arg: _t.Any) -> bool:
        return isinstance(arg, (_pd.DataFrame, _pd.Series, _pd.Index))

    @classmethod
    def names(cls, translatable: PandasT) -> list[_tt.NameType] | None:
        if isinstance(translatable, _pd.DataFrame):
            columns = translatable.columns
            if isinstance(columns, _pd.MultiIndex):
                return list(columns.get_level_values(-1))
            else:
                return list(columns)

        if isinstance(translatable, _pd.MultiIndex):
            names = [n for n in translatable.names if n is not None]
            return names or None

        return None if translatable.name is None else [translatable.name]

    @classmethod
    def extract(cls, translatable: PandasT, names: list[_tt.NameType]) -> dict[_tt.NameType, _abc.Sequence[_tt.IdType]]:
        if isinstance(translatable, _pd.DataFrame):
            ans = _defaultdict(list)
            for i, name in enumerate(translatable.columns):
                if name in names:
                    ans[name].extend(_float_to_int(translatable.iloc[:, i]))
            return dict(ans)
        elif isinstance(translatable, _pd.MultiIndex):
            # This will error on duplicate names, which is probably a good thing.
            return {name: list(translatable.unique(name)) for name in names}
        elif isinstance(translatable, (_pd.Series, _pd.Index)):
            _sequence.verify_names(len(translatable), names)
            translatable = _float_to_int(translatable)
            if len(names) == 1:
                return {names[0]: translatable.unique().tolist()}
            else:
                return _sequence.SequenceIO.extract(translatable, names)

        raise TypeError(f"This should not happen: {type(translatable)=}")  # pragma: no cover

    @classmethod
    def insert(
        cls,
        translatable: PandasT,
        names: list[_tt.NameType],
        tmap: _TranslationMap[_tt.NameType, _tt.SourceType, _tt.IdType],
        copy: bool,
    ) -> PandasT | None:
        if not copy:
            if isinstance(translatable, _pd.DataFrame):
                pass  # Ok
            elif isinstance(translatable, _pd.Series):
                pass  # Ok, for now.   # TODO(issues/170): PDEP-6 check
            else:
                raise _NotInplaceTranslatableError(translatable)

        if isinstance(translatable, _pd.Index):
            return _translate_index(translatable, names, tmap)

        if isinstance(translatable, _pd.DataFrame):
            return _translate_frame(translatable, names, tmap, copy)

        if isinstance(translatable, _pd.Series):
            return _translate_series(translatable, names, tmap, copy)

        raise TypeError(f"This should not happen: {type(translatable)=}")  # pragma: no cover


def _translate_pandas_vector(
    pvt: _VectorT,
    names: list[_tt.NameType],
    tmap: _TranslationMap[_tt.NameType, _tt.SourceType, _tt.IdType],
) -> list[str | None] | _VectorT:
    _sequence.verify_names(len(pvt), names)

    if len(names) == 1:
        # Optimization for single-name vectors. Faster than SequenceIO for pretty much every size.
        magic_dict = tmap[names[0]]

        mapping: dict[_tt.IdType, str | None]
        if _pd.api.types.is_numeric_dtype(pvt):
            # We don't need to cast float to int here, since hash(1.0) == hash(1). The cast in extract() is required
            # because some database drivers may complain, especially if they receive floats (especially NaN).
            mapping = {idx: magic_dict[idx] for idx in pvt.unique()}
            return pvt.map(mapping)
        else:
            mapping = {}
            data: list[_t.Any] = pvt.to_list()
            for i, idx in enumerate(data):
                if idx in mapping:
                    value = mapping[idx]
                else:
                    value = magic_dict[idx]
                    mapping[idx] = value
                data[i] = value

        return data
    else:
        return _sequence.translate_sequence(pvt, names, tmap)


def _translate_index(
    index: PandasT,
    names: list[_tt.NameType],
    tmap: _TranslationMap[_tt.NameType, _tt.SourceType, _tt.IdType],
) -> PandasT | None:
    if isinstance(index, _pd.MultiIndex):
        df = index.to_frame()
        _translate_frame(df, names, tmap, copy=False)
        return _pd.MultiIndex.from_frame(df, names=index.names)

    result = _translate_pandas_vector(index, names, tmap)
    if isinstance(result, _pd.Index):
        return result
    return _pd.Index(result, name=index.name, copy=False)


def _translate_frame(
    df: _pd.DataFrame,
    names: list[_tt.NameType],
    tmap: _TranslationMap[_tt.NameType, _tt.SourceType, _tt.IdType],
    copy: bool,
) -> _pd.DataFrame:
    if copy:
        df = df.copy()

    original_columns = df.columns

    try:
        df.columns = _pd.RangeIndex(len(original_columns))
        for name, int_col in zip(original_columns, df.columns, strict=True):
            if name in names:
                translated = _translate_pandas_vector(df[int_col], [name], tmap)
                df[int_col] = translated
    finally:
        df.columns = original_columns

    return df if copy else None


def _translate_series(
    series: _pd.Series,
    names: list[_tt.NameType],
    tmap: _TranslationMap[_tt.NameType, _tt.SourceType, _tt.IdType],
    copy: bool,
) -> _pd.Series | None:
    result = _translate_pandas_vector(series, names, tmap)
    if copy:
        if isinstance(result, _pd.Series):
            return result
        return _pd.Series(result, index=series.index, name=series.name, copy=False)

    with _warnings.catch_warnings():
        _warnings.simplefilter(action="ignore", category=FutureWarning)  # TODO(issues/170): PDEP-6 check
        series[:] = result
    return None


def _float_to_int(pvt: _VectorT) -> _VectorT:
    return pvt.dropna().astype(int) if _pd.api.types.is_float_dtype(pvt) else pvt
