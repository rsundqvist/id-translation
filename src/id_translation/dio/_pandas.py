from typing import Any, Dict, List, Optional, Sequence, TypeVar

import pandas as pd

from ..offline import TranslationMap
from ..types import IdType, NameType, SourceType
from ._data_structure_io import DataStructureIO
from ._sequence import SequenceIO, translate_sequence, verify_names

T = TypeVar("T", pd.DataFrame, pd.Series)


def _cast_series(series: pd.Series) -> pd.Series:
    return series.dropna().astype(int) if series.dtype == float else series


class PandasIO(DataStructureIO):
    """Implementation for Pandas data types."""

    @staticmethod
    def handles_type(arg: Any) -> bool:
        return isinstance(arg, (pd.DataFrame, pd.Series))

    @staticmethod
    def extract(translatable: T, names: List[NameType]) -> Dict[NameType, Sequence[IdType]]:
        if isinstance(translatable, pd.DataFrame):
            return {name: _cast_series(translatable[name]).tolist() for name in names}
        else:
            return SequenceIO.extract(_cast_series(translatable), names)

    @staticmethod
    def insert(
        translatable: T, names: List[NameType], tmap: TranslationMap[NameType, SourceType, IdType], copy: bool
    ) -> Optional[T]:
        translatable = translatable.copy() if copy else translatable

        if isinstance(translatable, pd.DataFrame):
            for name in names:
                translatable[name] = translatable[name].map(tmap[name].get)
        else:
            verify_names(len(translatable), names)
            translatable.update(pd.Series(translate_sequence(translatable, names, tmap), index=translatable.index))

        return translatable if copy else None
