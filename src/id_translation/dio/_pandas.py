from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, TypeVar

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
            ans = defaultdict(list)
            for i, name in enumerate(translatable.columns):
                if name in names:
                    ans[name].extend(_cast_series(translatable.iloc[:, i]))
            return dict(ans)
        else:
            return SequenceIO.extract(_cast_series(translatable), names)

    @staticmethod
    def insert(
        translatable: T, names: List[NameType], tmap: TranslationMap[NameType, SourceType, IdType], copy: bool
    ) -> Optional[T]:
        translatable = translatable.copy() if copy else translatable

        if isinstance(translatable, pd.DataFrame):
            for i, name in enumerate(translatable.columns):
                if name in names:
                    translatable.iloc[:, i] = _translate_series(translatable.iloc[:, i], [name], tmap)
        else:
            verify_names(len(translatable), names)
            translatable[:] = _translate_series(translatable, names, tmap)

        return translatable if copy else None


def _translate_series(
    series: pd.Series, names: List[NameType], tmap: TranslationMap[NameType, SourceType, IdType]
) -> Iterable[Optional[str]]:
    verify_names(len(series), names)

    if len(names) == 1 and len(series) > 100:
        # Optimization for large series. Suboptimal if "many" values are
        # unique. Not worth the additional overhead for small series.
        magic_dict = tmap[names[0]]
        mapping = {idx: magic_dict.get(idx) for idx in series.unique()}
        return series.map(mapping)  # type: ignore[no-any-return]
    else:
        return translate_sequence(series, names, tmap)
