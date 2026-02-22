"""Integration for `Polars <https://pola.rs/>`_ types."""

import typing as _t
import warnings as _w
from collections import abc as _abc

import polars as _pl
from rics.misc import tname as _tname

from id_translation import dio as _dio
from id_translation import types as _tt
from id_translation.dio.exceptions import NotInplaceTranslatableError as _NotInplaceTranslatableError
from id_translation.offline import MagicDict as _MagicDict
from id_translation.offline import TranslationMap as _TranslationMap

PolarsT = _t.TypeVar("PolarsT", _pl.DataFrame, _pl.Series)
"""Supported ``polars`` types."""


class PolarsIO(_dio.DataStructureIO[PolarsT, str, _tt.SourceType, _tt.IdType]):
    """Optional IO implementation for ``polars`` types.

    Args:
        fast: Apply optimizations if ``True``. Can be faster for large amounts of data but is much less flexible.
    """

    def __init__(
        self,
        *,
        fast: bool = False,
    ) -> None:
        self._fast = fast

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

    @classmethod
    def extract(cls, translatable: PolarsT, names: list[str]) -> dict[str, _abc.Sequence[_tt.IdType]]:
        def extract(series: _pl.Series) -> _abc.Sequence[_tt.IdType]:
            return cls.obj_to_str(series).unique().to_list()

        if isinstance(translatable, _pl.Series):
            if len(names) != 1:
                msg = f"{len(names)=} != 1 is not supported for {_tname(translatable, include_module=True)}"
                raise NotImplementedError(msg)
            return {names[0]: extract(translatable)}
        else:
            return {n: extract(translatable[n]) for n in names}

    def insert(
        self,
        translatable: PolarsT,
        names: list[str],
        tmap: _TranslationMap[str, _tt.SourceType, _tt.IdType],
        copy: bool,
    ) -> PolarsT | None:
        if not copy and isinstance(translatable, _pl.Series):
            raise _NotInplaceTranslatableError(translatable)

        if isinstance(translatable, _pl.DataFrame):
            translated_columns = {name: self._translate_series(translatable[name], tmap[name]) for name in names}
            if copy:
                return translatable.with_columns(**translated_columns)
            else:
                for name, column in translated_columns.items():
                    translatable.replace_column(translatable.columns.index(name), column)
                return None
        else:
            return self._translate_series(translatable, tmap[names[0]])

    def _translate_series(self, series: _pl.Series, magic_dict: _MagicDict[_tt.IdType]) -> _pl.Series:
        if self._fast:
            return series.replace_strict(magic_dict.real, return_dtype=_pl.String, default="")

        # Create the mappings before Polars can disappear into Rust, where the MagicDict logic will disappear. For
        # the base case this is fine, but things like Transformer.try_add_missing_key will break.
        series = self.obj_to_str(series)
        mapping = {idx: magic_dict[idx] for idx in series.unique()}
        return series.replace_strict(mapping, return_dtype=_pl.String)

    @staticmethod
    def obj_to_str(series: _pl.Series) -> _pl.Series:
        """Utility method for dtype conversion.

        Will cast ``polars.Object`` to ``polars.String``, which is slow but required for translation. Elements are
        mapped using the regular builtin ``str`` function.

        This method is never called when ``fast=True``.

        Returns:
            A series which does _not_ use the ``polars.Object`` dtype. No changes are made if any other dtype is used.
        """
        if series.dtype != _pl.Object:
            return series

        with _w.catch_warnings():
            _w.filterwarnings("ignore", category=_pl.exceptions.PolarsInefficientMapWarning)
            return series.map_elements(str, return_dtype=_pl.String)
