"""Integration for `Pandas <https://pandas.pydata.org/>`_ types."""

import typing as _t
import warnings as _warnings
from collections import abc as _abc
from contextlib import contextmanager as _contextmanager
from uuid import UUID as _UUID

import numpy as _np
import pandas as _pd

from id_translation import _uuid_utils
from id_translation import dio as _dio
from id_translation import types as _tt
from id_translation.dio.default import _sequence
from id_translation.dio.exceptions import NotInplaceTranslatableError as _NotInplaceTranslatableError
from id_translation.offline import MagicDict as _MagicDict
from id_translation.offline import TranslationMap as _TranslationMap

PandasT = _t.TypeVar("PandasT", _pd.DataFrame, _pd.Series, _pd.Index, _pd.MultiIndex)
"""Supported ``pandas`` types."""

# Types with ``ndim==1``.
_PandasVectorT = _t.TypeVar("_PandasVectorT", _pd.Series, _pd.Index)

_NumpyVector = _np.ndarray[tuple[int], _np.dtype[_t.Any]]
_ExtractArgType: _t.TypeAlias = _pd.DataFrame | _pd.Series | _pd.Index | _NumpyVector


class PandasIO(_dio.DataStructureIO[PandasT, _tt.NameType, _tt.SourceType, _tt.IdType]):
    """Optional IO implementation for ``pandas`` types.

    Args:
        level: Column level to use as names when translating a ``DataFrame`` with ``MultiIndex`` columns. See
            :meth:`pandas.MultiIndex.get_level_values` for details. Ignored otherwise.
        missing_as_nan: If set, unknown IDs will be `NaN`. Grouping operations will
            `typically drop <https://pandas.pydata.org/docs/dev/user_guide/groupby.html#na-group-handling>`_
            `NaN` values. If ``False``, placeholders such as ``'<Failed: id=-1>'`` will be used instead.
            Default is ``True`` if ``as_category=True``, ``False`` otherwise.
        as_category: Set `dtype='category'` in the result. See :ref:`Categorical translation` for details.

    Categorical translation
    -----------------------
    Setting ``as_category=True`` converts the resultant translations to a
    `categorical <https://pandas.pydata.org/docs/user_guide/categorical.html>`_
    data type. The returned :class:`pandas.CategoricalDtype` will be :attr:`~pandas.CategoricalDtype.ordered`, with the
    :attr:`~pandas.CategoricalDtype.categories` set to all :attr:`real translations <id_translation.offline.MagicDict.real>`. If
    ``missing_as_nan=False``, the `categories` may also include placeholders.

    Certain fetchers, such as the :class:`MemoryFetcher(return_all=True) <id_translation.fetching.MemoryFetcher>`, will return more IDs than
    requested. In this case the `categories` may also include values not present in the input data. This may also happen
    if data was prepared with :meth:`Translator.go_offline <id_translation.Translator.go_offline>`, or if multiple columns were
    :ref:`mapped <mapping-primer>`
    to the same source.
    """

    def __init__(
        self,
        *,
        level: str | int = -1,
        missing_as_nan: bool | None = None,
        as_category: bool = False,
    ) -> None:
        if missing_as_nan is None:
            missing_as_nan = as_category

        self._level = level
        self._missing_as_nan = missing_as_nan
        self._as_category = as_category

    priority = 1999

    @classmethod
    def handles_type(cls, arg: _t.Any) -> bool:
        return isinstance(arg, (_pd.DataFrame, _pd.Series, _pd.Index))

    def names(self, translatable: PandasT) -> list[_tt.NameType] | None:
        if isinstance(translatable, _pd.DataFrame):
            columns = translatable.columns
            if isinstance(columns, _pd.MultiIndex):
                with self._reraise_with_notes(translatable, "column.names", columns.names, IndexError, KeyError):
                    return columns.unique(self._level).to_list()  # type: ignore[no-any-return]
            else:
                return columns.to_list()  # type: ignore[no-any-return]

        if isinstance(translatable, _pd.MultiIndex):
            names = [n for n in translatable.names if n is not None]
            return names or None

        name = translatable.name
        if name is None:
            return None
        if isinstance(name, tuple):
            # Produced by selecting a single column series from a MultiIndex-column frame.
            with self._reraise_with_notes(translatable, "name", name, IndexError, TypeError):
                name = name[self._level]  # type: ignore[index]

        return [name]

    def extract(
        self,
        translatable: PandasT,
        names: list[_tt.NameType],
    ) -> dict[_tt.NameType, _abc.Sequence[_tt.IdType]]:
        if isinstance(translatable, _pd.MultiIndex):
            translatable = translatable.to_frame(index=False, allow_duplicates=True)

        if isinstance(translatable, _pd.DataFrame):
            if isinstance(translatable.columns, _pd.MultiIndex):
                rv: dict[_tt.NameType, _abc.Sequence[_tt.IdType]] = {}
                level_values = translatable.columns.get_level_values(self._level)
                for name in level_values.unique():
                    rv[name] = _extract(translatable.loc[:, level_values == name])
                return rv

            return {name: _extract(translatable[name]) for name in names}
        elif isinstance(translatable, (_pd.Series, _pd.Index)):
            _sequence.verify_names(len(translatable), names)
            if len(names) == 1:
                return {names[0]: _extract(translatable)}
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

    @staticmethod
    def _join_map(pvt: _PandasVectorT, magic_dict: _MagicDict[_tt.IdType]) -> dict[_tt.IdType, str]:
        """The dict to join `pvt` against: the backing dict, or a key-normalizing view of it.

        Joining `real` directly requires that `pvt` uses the same ID representation as its keys. UUID heuristics
        exist because it often does not, so normalize once per unique ID instead of letting every row miss the join
        and fall back to the per-ID Python path.
        """
        real = magic_dict.real
        if not magic_dict.enable_uuid_heuristics or len(pvt) == 0 or isinstance(next(iter(pvt)), _UUID):
            return real  # Heuristics are inert, or `pvt` already holds UUIDs (as `real` does).

        normalized: dict[_tt.IdType, str] = {}
        for idx in pvt.unique().tolist():
            # Exact key first, then the cast key -- `real_get` resolves in that order, and `real` may hold both (a
            # transformer can add keys without going through `MagicDict.__setitem__`). Cast-key-first would shadow
            # the exact match and translate differently than the scalar path.
            if idx in real:
                normalized[idx] = real[idx]
            elif (key := _uuid_utils.try_cast_one(idx)) in real:
                normalized[idx] = real[key]

        # Never return an empty map: pandas infers the result dtype from the mapped values, so an empty one yields
        # `object` (which propagates -- it poisons dask's meta inference). Any hit `real` adds back is a real hit;
        # misses are handled by the caller either way.
        return normalized or real

    def _translate_pandas_vector(
        self,
        pvt: _PandasVectorT,
        names: list[_tt.NameType],
        tmap: _TranslationMap[_tt.NameType, _tt.SourceType, _tt.IdType],
    ) -> list[str | None] | _PandasVectorT:
        _sequence.verify_names(len(pvt), names)

        if len(names) > 1:
            if len(set(names)) == 1:
                names = [names[0]]
            elif missing_as_nan := self._missing_as_nan:
                msg = f"{missing_as_nan=} not supported for {names=}"
                raise NotImplementedError(msg)
            elif as_category := self._as_category:
                msg = f"{as_category=} not supported for {names=}"
                raise NotImplementedError(msg)
            else:
                return _sequence.translate_sequence(pvt, names, tmap)

        # Optimization for single-name vectors. Faster than SequenceIO for pretty much every size.
        magic_dict: _MagicDict[_tt.IdType] = tmap[names[0]]

        # Join against the backing dict, then run the MagicDict logic (defaults, transformers) only for the IDs the
        # join missed. Real translations are never NaN, so NaN means "not a direct hit".
        join_map = self._join_map(pvt, magic_dict)
        rv = pvt.map(join_map)

        extra: dict[_tt.IdType, str | None] = {}
        mask = rv.isna()
        if mask.any():
            get_item = magic_dict.real_get if self._missing_as_nan else magic_dict.__getitem__
            extra = {idx: get_item(idx) for idx in pvt[mask].unique().tolist()}
            if isinstance(pvt.dtype, _pd.CategoricalDtype):
                # Combining two categoricals with different categories upcasts to object, so remap in one pass
                # instead. Cheap: `map` resolves a categorical per category, not per row.
                rv = pvt.map({**join_map, **extra})
            else:
                rv = rv.where(~mask, pvt.map(extra))

        if self._as_category:
            translations = {*magic_dict.real.values()}
            if not self._missing_as_nan:
                translations.update(extra.values())  # type: ignore[arg-type]

            categories = sorted(translations)
            dtype = _pd.CategoricalDtype(categories, ordered=True)
            rv = rv.astype(dtype)

        return rv

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

        # This typically means we're translating multiple names.
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
        columns = (
            original_columns.get_level_values(self._level)
            if isinstance(original_columns, _pd.MultiIndex)
            else original_columns
        )
        df.columns = _pd.RangeIndex(len(original_columns))

        try:
            for tmp_col, name in enumerate(columns):
                if name in names:
                    translated = self._translate_pandas_vector(df[tmp_col], [name], tmap)
                    df[tmp_col] = translated
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

            # This typically means we're translating multiple names.
            return _pd.Series(result, index=series.index, name=series.name, copy=False)

        with _warnings.catch_warnings():
            # TODO: Stop suppressing this warning.
            _warnings.simplefilter(action="ignore", category=FutureWarning)
            series[:] = result
        return None

    @_contextmanager
    def _reraise_with_notes(
        self, translatable: PandasT, attr_name: str, attr_value: _t.Any, *exceptions: type[Exception]
    ) -> _t.Generator[None, None, None]:
        try:
            yield
        except exceptions as exc:
            exc.add_note(f"{type(self).__name__}.level={self._level!r}")
            exc.add_note(f"{type(translatable)}.{attr_name}={attr_value!r}")
            raise exc from None


def _extract(translatable: _ExtractArgType) -> list[_tt.IdType]:
    """Many database drivers dislike floats, especially NaN."""
    try:
        unique: _NumpyVector = _np.unique(translatable, axis=None)
    except TypeError as exc:
        if (
            isinstance(exc, TypeError)
            and not isinstance(translatable, _np.ndarray)
            and _pd.api.types.is_object_dtype(translatable.dtypes)
        ):
            # Last-ditch effort. Mixed dtypes will raise if not comparable (e.g., UUID/str; np.unique will sort). Cast
            # to str is both hacky and slow, but if you're mixing dtypes you probably don't care anyway.
            return _extract(translatable.astype(str))
        else:
            exc.add_note(f"{type(translatable)=}")
            raise

    if _np.issubdtype(unique.dtype, _np.floating):
        unique = unique[_np.isfinite(unique)].astype(int)

    return unique.tolist()
