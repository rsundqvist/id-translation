"""Integration for `Polars <https://pola.rs/>`_ types."""

import typing as _t

import polars as pl

from id_translation import dio as _dio
from id_translation import types as _tt
from id_translation.offline import TranslationMap as _TranslationMap

PolarsT = _t.TypeVar("PolarsT", pl.DataFrame, pl.Series)
"""Supported ``polars`` types."""


class PolarsIO(_dio.DataStructureIO[PolarsT, str, _tt.SourceType, _tt.IdType]):
    """IO implementation for ``polars`` types."""

    @classmethod
    def handles_type(cls, arg: _t.Any) -> bool:
        if isinstance(arg, pl.LazyFrame):
            raise NotImplementedError("polars.LazyFrame not supported")
        return isinstance(arg, (pl.DataFrame, pl.Series))

    @classmethod
    def names(cls, translatable: PolarsT) -> list[str] | None:
        if isinstance(translatable, pl.DataFrame):
            return list(translatable.columns)

        return None if translatable.name is None else [translatable.name]

    @classmethod
    def extract(cls, translatable: PolarsT, names: list[str]) -> dict[str, _t.Sequence[_tt.IdType]]:
        if isinstance(translatable, pl.Series):
            if len(names) != 1:
                raise RuntimeError(f"{len(names)=} != 1 is not supported for polars.Series")
            return {names[0]: translatable.to_list()}
        else:
            # Unlike Pandas, polars==0.20.16 raises DuplicateError on duplicate column names.
            name_to_ids = translatable[names].to_dict(as_series=False)
            return name_to_ids  # type: ignore[return-value]

    @classmethod
    def insert(
        cls,
        translatable: PolarsT,
        names: list[str],
        tmap: _TranslationMap[str, _tt.SourceType, _tt.IdType],
        copy: bool,
    ) -> PolarsT | None:
        if not copy and isinstance(translatable, pl.Series):
            from id_translation.dio.exceptions import NotInplaceTranslatableError

            raise NotInplaceTranslatableError(translatable)

        def _translate_series(series: pl.Series, name: str) -> pl.Series:
            # Create the mappings before Polars can disappear into Rust, where the MagicDict logic will disappear. For
            # the base case this is fine, but things like Transformer.try_add_missing_key will break.

            magic_dict = tmap[name]

            try:
                mapping = {idx: magic_dict[idx] for idx in series.unique()}
                return series.replace(mapping)
            except pl.exceptions.InvalidOperationError:
                # InvalidOperationError: `unique` operation not supported for dtype `object`

                mapping = {idx: magic_dict[idx] for idx in set(series)}
                return pl.Series(values=[mapping[idx] for idx in series], name=name)

        if isinstance(translatable, pl.DataFrame):
            translated_columns = {name: _translate_series(translatable[name], name) for name in names}
            if copy:
                return translatable.with_columns(**translated_columns)
            else:
                for name, column in translated_columns.items():
                    translatable.replace_column(translatable.columns.index(name), column)
                return None
        else:
            return _translate_series(translatable, names[0])
