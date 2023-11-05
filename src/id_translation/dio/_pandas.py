import warnings
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, TypeVar, Union

import pandas as pd

from ..offline import TranslationMap
from ..types import IdType, NameType, SourceType
from ._data_structure_io import DataStructureIO
from ._sequence import SequenceIO, translate_sequence, verify_names
from .exceptions import NotInplaceTranslatableError

T = TypeVar("T", pd.DataFrame, pd.Series)


def _cast_series(series: pd.Series) -> pd.Series:
    return series.dropna().astype(int) if series.dtype == float else series


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
                    ans[name].extend(_cast_series(translatable.iloc[:, i]))
            return dict(ans)
        elif isinstance(translatable, pd.Series):
            return SequenceIO.extract(_cast_series(translatable), names)
        elif isinstance(translatable, pd.MultiIndex):
            # This will error on duplicate names, which is probably a good thing.
            return {name: list(translatable.unique(name)) for name in names}
        elif isinstance(translatable, pd.Index):
            return SequenceIO.extract(translatable, names)

        raise TypeError(f"This should not happen: {type(translatable)=}")

    @staticmethod
    def insert(
        translatable: T, names: List[NameType], tmap: TranslationMap[NameType, SourceType, IdType], copy: bool
    ) -> Optional[T]:
        if isinstance(translatable, (pd.DataFrame, pd.Series)):
            if copy:
                translatable = translatable.copy()
        else:  # Index-type translatable
            if not copy:
                raise NotInplaceTranslatableError(translatable)  # TODO(issues/170): PDEP-6 check

        if isinstance(translatable, pd.DataFrame):
            for i, name in enumerate(translatable.columns):
                if name in names:
                    translatable.iloc[:, i] = _translate_series(translatable.iloc[:, i], [name], tmap)
        elif isinstance(translatable, pd.Series):
            verify_names(len(translatable), names)
            result = _translate_series(translatable, names, tmap)
            with warnings.catch_warnings():
                warnings.simplefilter(action="ignore", category=FutureWarning)  # TODO(issues/170): PDEP-6 check
                translatable[:] = result
        elif isinstance(translatable, pd.MultiIndex):
            df = translatable.to_frame()
            PandasIO.insert(df, names, tmap, copy=False)
            translatable = pd.MultiIndex.from_frame(df, names=translatable.names)
        elif isinstance(translatable, pd.Index):
            translatable = pd.Index(_translate_series(translatable, names, tmap), name=translatable.name)
        else:
            raise TypeError(f"This should not happen: {type(translatable)=}")

        return translatable if copy else None


def _translate_series(
    # Not MultiIndex
    series: Union[pd.Series, pd.Index],
    names: List[NameType],
    tmap: TranslationMap[NameType, SourceType, IdType],
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
