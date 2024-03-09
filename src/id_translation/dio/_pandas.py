import warnings
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, TypeVar, Union

import pandas as pd
from pandas.api.types import is_float_dtype, is_numeric_dtype

from ..offline import TranslationMap
from ..types import IdType, NameType, SourceType
from ._data_structure_io import DataStructureIO
from ._sequence import SequenceIO, translate_sequence, verify_names
from .exceptions import NotInplaceTranslatableError

T = TypeVar("T", pd.DataFrame, pd.Series, pd.Index, pd.MultiIndex)
PandasVectorT = TypeVar("PandasVectorT", pd.Series, pd.Index)


class PandasIO(DataStructureIO):
    """Implementation for Pandas data types."""

    @staticmethod
    def handles_type(arg: Any) -> bool:
        return isinstance(arg, (pd.DataFrame, pd.Series, pd.Index))

    @staticmethod
    def names(translatable: T) -> Optional[List[NameType]]:
        if isinstance(translatable, pd.DataFrame):
            return list(translatable.columns)

        if isinstance(translatable, pd.MultiIndex):
            names = translatable.names
            return list(names) if any(names) else None

        return None if translatable.name is None else [translatable.name]

    @staticmethod
    def extract(translatable: T, names: List[NameType]) -> Dict[NameType, Sequence[IdType]]:
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

    @staticmethod
    def insert(
        translatable: T, names: List[NameType], tmap: TranslationMap[NameType, SourceType, IdType], copy: bool
    ) -> Optional[T]:
        if not copy:
            if isinstance(translatable, pd.DataFrame):
                pass  # Ok
            elif isinstance(translatable, pd.Series):
                pass  # Ok, for now.   # TODO(issues/170): PDEP-6 check
            else:
                raise NotInplaceTranslatableError(translatable)

        if isinstance(translatable, pd.MultiIndex):
            df = translatable.to_frame()
            PandasIO.insert(df, names, tmap, copy=False)
            return pd.MultiIndex.from_frame(df, names=translatable.names)

        if isinstance(translatable, pd.Index):
            result = _translate_pandas_vector(translatable, names, tmap)
            if isinstance(result, pd.Index):
                return result
            return pd.Index(result, name=translatable.name, copy=False)

        if isinstance(translatable, pd.DataFrame):
            if copy:
                translatable = translatable.copy()

            for i, name in enumerate(translatable.columns):
                if name in names:
                    translatable.iloc[:, i] = _translate_pandas_vector(translatable.iloc[:, i], [name], tmap)

            return translatable if copy else None

        if isinstance(translatable, pd.Series):
            result = _translate_pandas_vector(translatable, names, tmap)

            if copy:
                if isinstance(result, pd.Series):
                    return result
                return pd.Series(result, index=translatable.index, name=translatable.name, copy=False)

            with warnings.catch_warnings():
                warnings.simplefilter(action="ignore", category=FutureWarning)  # TODO(issues/170): PDEP-6 check
                translatable[:] = result
            return None

        raise TypeError(f"This should not happen: {type(translatable)=}")  # pragma: no cover


def _translate_pandas_vector(
    pvt: PandasVectorT,
    names: List[NameType],
    tmap: TranslationMap[NameType, SourceType, IdType],
) -> Union[List[Optional[str]], PandasVectorT]:
    verify_names(len(pvt), names)

    if len(names) == 1:
        # Optimization for single-name vectors. Faster than SequenceIO for pretty much every size.
        magic_dict = tmap[names[0]]

        mapping: Dict[IdType, Optional[str]]
        if is_numeric_dtype(pvt):
            # We don't need to cast float to int here, since hash(1.0) == hash(1). The cast in extract() is required
            # because some database drivers may complain, especially if they receive floats (especially NaN).
            mapping = {idx: magic_dict.get(idx) for idx in pvt.unique()}
            return pvt.map(mapping)
        else:
            mapping = {}
            data: List[Any] = pvt.to_list()
            for i, idx in enumerate(data):
                if idx in mapping:
                    value = mapping[idx]
                else:
                    value = magic_dict.get(idx)
                    mapping[idx] = value
                data[i] = value

        return data
    else:
        return translate_sequence(pvt, names, tmap)


def _float_to_int(pvt: PandasVectorT) -> PandasVectorT:
    return pvt.dropna().astype(int) if is_float_dtype(pvt) else pvt
