"""Types used for offline translation."""

from collections.abc import Sequence as _Sequence
from dataclasses import dataclass as _dataclass
from typing import TYPE_CHECKING
from typing import Any as _Any
from typing import Generic as _Generic
from typing import Union as _Union

import pandas as pd

from ..types import ID, IdType, SourceType

if TYPE_CHECKING:
    from ._format import Format

FormatType = _Union[str, "Format"]

PlaceholdersTuple = tuple[str, ...]
TranslatedIds = dict[IdType, str]  # {id: translation}


@_dataclass
class PlaceholderTranslations(_Generic[SourceType]):
    """Matrix of ID translation components returned by fetchers."""

    MakeTypes = _Union["PlaceholderTranslations", pd.DataFrame, dict[str, _Sequence]]  # type: ignore[type-arg]

    source: SourceType
    """Source from which translations were retrieved."""
    placeholders: PlaceholdersTuple
    """Names of placeholders in the order in which they appear in `records`."""
    records: _Sequence[_Sequence[_Any]]
    """Matrix of shape `N x M` where `N` is the number of IDs returned and `M` is the length of `placeholders`."""
    id_pos: int = -1
    """Position if the the ID placeholder in `placeholders`."""

    @classmethod
    def make(cls, source: SourceType, data: MakeTypes) -> "PlaceholderTranslations[SourceType]":
        """Try to make in instance from arbitrary input data.

        Args:
            source: Source label for the translations.
            data: Some data to convert to a PlaceholderTranslations instance.

        Returns:
            A new PlaceholderTranslations instance.

        Raises:
            TypeError: If `data` cannot be converted.
        """
        if isinstance(data, PlaceholderTranslations):  # pragma: no cover
            return data

        if isinstance(data, pd.DataFrame):
            return cls.from_dataframe(source, data)
        if isinstance(data, dict):
            return cls.from_dict(source, data)

        raise TypeError(data)  # pragma: no cover

    def to_dict(self, max_rows: int = 0) -> dict[str, _Sequence[_Any]]:
        """Create a dict representation of the translations."""
        records = self.records[:max_rows] if max_rows else self.records
        return {placeholder: [row[i] for row in records] for i, placeholder in enumerate(self.placeholders)}

    @staticmethod
    def to_dicts(
        source_translations: "SourcePlaceholderTranslations[SourceType]",
        max_rows: int = 0,
    ) -> dict[SourceType, dict[str, _Sequence[_Any]]]:
        """Create a nested dict representation of the translations."""
        return {source: translations.to_dict(max_rows) for source, translations in source_translations.items()}

    @classmethod
    def from_dataframe(cls, source: SourceType, data: pd.DataFrame) -> "PlaceholderTranslations[SourceType]":
        """Create instance from a pandas DataFrame."""
        return cls(
            source,
            placeholders=tuple(data),
            records=data.to_numpy().tolist(),
            id_pos=data.columns.get_loc(ID) if ID in data else -1,
        )

    @classmethod
    def from_dict(cls, source: SourceType, data: dict[str, _Sequence[_Any]]) -> "PlaceholderTranslations[SourceType]":
        """Create instance from a dict."""
        return cls.from_dataframe(source, pd.DataFrame.from_dict(data))


SourcePlaceholderTranslations = dict[SourceType, PlaceholderTranslations[SourceType]]
