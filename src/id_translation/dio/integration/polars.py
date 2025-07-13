"""Integration for `Polars <https://pola.rs/>`_ types."""

import typing as _t
import warnings as _w
from collections import abc as _abc

import polars as _pl

from id_translation import dio as _dio
from id_translation import types as _tt
from id_translation.dio.exceptions import NotInplaceTranslatableError as _NotInplaceTranslatableError
from id_translation.offline import TranslationMap as _TranslationMap

PolarsT = _t.TypeVar("PolarsT", _pl.DataFrame, _pl.Series)
"""Supported ``polars`` types."""


class PolarsIO(_dio.DataStructureIO[PolarsT, str, _tt.SourceType, _tt.IdType]):
    """Optional IO implementation for ``polars`` types."""

    priority = 1990

    @classmethod
    def handles_type(cls, arg: _t.Any) -> bool:
        if isinstance(arg, _pl.LazyFrame):
            raise NotImplementedError("polars.LazyFrame not supported")
        return isinstance(arg, (_pl.DataFrame, _pl.Series))

    @classmethod
    def names(cls, translatable: PolarsT) -> list[str] | None:
        if isinstance(translatable, _pl.DataFrame):
            return list(translatable.columns)

        return None if translatable.name is None else [translatable.name]

    @staticmethod
    def _obj_to_str(series: _pl.Series) -> _pl.Series:
        if series.dtype == _pl.Object:
            with _w.catch_warnings():
                _w.filterwarnings("ignore", category=_pl.exceptions.PolarsInefficientMapWarning)
                series = series.map_elements(str, return_dtype=_pl.String)
        return series

    @classmethod
    def extract(cls, translatable: PolarsT, names: list[str]) -> dict[str, _abc.Sequence[_tt.IdType]]:
        def extract(series: _pl.Series) -> _abc.Sequence[_tt.IdType]:
            return cls._obj_to_str(series).unique().to_list()

        if isinstance(translatable, _pl.Series):
            if len(names) != 1:
                raise RuntimeError(f"{len(names)=} != 1 is not supported for polars.Series")
            return {names[0]: extract(translatable)}
        else:
            return {n: extract(translatable[n]) for n in names}

    @classmethod
    def insert(
        cls,
        translatable: PolarsT,
        names: list[str],
        tmap: _TranslationMap[str, _tt.SourceType, _tt.IdType],
        copy: bool,
    ) -> PolarsT | None:
        if not copy and isinstance(translatable, _pl.Series):
            raise _NotInplaceTranslatableError(translatable)

        def _translate_series(series: _pl.Series, name: str) -> _pl.Series:
            # Create the mappings before Polars can disappear into Rust, where the MagicDict logic will disappear. For
            # the base case this is fine, but things like Transformer.try_add_missing_key will break.
            magic_dict = tmap[name]
            series = cls._obj_to_str(series)
            mapping = {idx: magic_dict[idx] for idx in series.unique()}
            return series.replace_strict(mapping, return_dtype=_pl.String)

        if isinstance(translatable, _pl.DataFrame):
            translated_columns = {name: _translate_series(translatable[name], name) for name in names}
            if copy:
                return translatable.with_columns(**translated_columns)
            else:
                for name, column in translated_columns.items():
                    translatable.replace_column(translatable.columns.index(name), column)
                return None
        else:
            return _translate_series(translatable, names[0])
