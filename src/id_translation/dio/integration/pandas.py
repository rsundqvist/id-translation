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
    """Optional IO implementation for ``pandas`` types.

    Args:
        missing_as_nan: If ``True``, missing IDs will be ``NaN``. For use with :meth:`~pandas.DataFrame.dropna()`. If
            ``False`` (the default), dummy translations such as ``<Failed: id=np.float64(nan)>`` are used instead.
    """

    priority = 1999

    def __init__(
        self,
        *,
        missing_as_nan: bool = False,
    ) -> None:
        self._missing_as_nan = missing_as_nan

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

    def insert(
        self,
        translatable: PandasT,
        names: list[_tt.NameType],
        tmap: _TranslationMap[_tt.NameType, _tt.SourceType, _tt.IdType],
        copy: bool,
    ) -> PandasT | None:
        if isinstance(translatable, _pd.Index):
            if not copy:
                raise _NotInplaceTranslatableError(translatable)
            return self._translate_index(translatable, names, tmap)

        if isinstance(translatable, _pd.DataFrame):
            return self._translate_frame(translatable, names, tmap, copy)

        if isinstance(translatable, _pd.Series):
            if not copy:
                msg = self._check_pdep_6(translatable)
                if msg:
                    exc = _NotInplaceTranslatableError(translatable)
                    exc.add_note(f"Hint: {msg}")
                    raise exc
            return self._translate_series(translatable, names, tmap, copy)

        raise TypeError(f"This should not happen: {type(translatable)=}")  # pragma: no cover

    @classmethod
    def _check_pdep_6(cls, series: _pd.Series) -> str | None:
        """Check if # https://pandas.pydata.org/pdeps/0006-ban-upcasting.html applies."""
        copy = series.head(1)
        try:
            copy[:] = "<string>"  # See _translate_series
            return None
        except TypeError as e:
            return str(e)

    def _translate_pandas_vector(
        self,
        pvt: _VectorT,
        names: list[_tt.NameType],
        tmap: _TranslationMap[_tt.NameType, _tt.SourceType, _tt.IdType],
    ) -> list[str | None] | _VectorT:
        _sequence.verify_names(len(pvt), names)

        if len(names) > 1:
            if missing_as_nan := self._missing_as_nan:
                if len(set(names)) == 1:
                    return self._translate_pandas_vector(pvt, [names[0]], tmap)

                msg = f"{missing_as_nan=} not supported for {names=}"
                raise NotImplementedError(msg)
            return _sequence.translate_sequence(pvt, names, tmap)

        # Optimization for single-name vectors. Faster than SequenceIO for pretty much every size.
        magic_dict = tmap[names[0]]
        get_item = magic_dict.real.get if self._missing_as_nan else magic_dict.__getitem__

        mapping: dict[_tt.IdType, str | None]
        if _pd.api.types.is_numeric_dtype(pvt):
            # We don't need to cast float to int here, since hash(1.0) == hash(1). The cast in extract() is required
            # because some database drivers may complain, especially if they receive floats (especially NaN).
            mapping = {idx: get_item(idx) for idx in pvt.unique()}
            return pvt.map(mapping)

        mapping = {}
        data: list[_t.Any] = pvt.to_list()
        for i, idx in enumerate(data):
            if idx in mapping:
                value = mapping[idx]
            else:
                value = get_item(idx)
                mapping[idx] = value
            data[i] = value

        return data

    def _translate_index(
        self,
        index: PandasT,
        names: list[_tt.NameType],
        tmap: _TranslationMap[_tt.NameType, _tt.SourceType, _tt.IdType],
    ) -> PandasT | None:
        if isinstance(index, _pd.MultiIndex):
            df = index.to_frame()
            self._translate_frame(df, names, tmap, copy=False)
            return _pd.MultiIndex.from_frame(df, names=index.names)

        result = self._translate_pandas_vector(index, names, tmap)
        if isinstance(result, _pd.Index):
            return result
        return _pd.Index(result, name=index.name, copy=False)

    def _translate_frame(
        self,
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
                    translated = self._translate_pandas_vector(df[int_col], [name], tmap)
                    df[int_col] = translated
        finally:
            df.columns = original_columns

        return df if copy else None

    def _translate_series(
        self,
        series: _pd.Series,
        names: list[_tt.NameType],
        tmap: _TranslationMap[_tt.NameType, _tt.SourceType, _tt.IdType],
        copy: bool,
    ) -> _pd.Series | None:
        result = self._translate_pandas_vector(series, names, tmap)
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
