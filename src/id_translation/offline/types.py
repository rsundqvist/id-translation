"""Types used for offline translation."""
import dataclasses
from typing import TYPE_CHECKING, Any as _Any, Dict, Generic as _Generic, Sequence, Tuple, Union

import pandas as pd

from ..types import ID, IdType, SourceType

if TYPE_CHECKING:
    from ._format import Format

FormatType = Union[str, "Format"]

PlaceholdersTuple = Tuple[str, ...]
TranslatedIds = Dict[IdType, str]  # {id: translation}


@dataclasses.dataclass
class PlaceholderTranslations(_Generic[SourceType]):
    """Matrix of ID translation components returned by fetchers."""

    MakeTypes = Union["PlaceholderTranslations", pd.DataFrame, Dict[str, Sequence]]  # type: ignore[type-arg]

    source: SourceType
    """Source from which translations were retrieved."""
    placeholders: PlaceholdersTuple
    """Names of placeholders in the order in which they appear in `records`."""
    records: Sequence[Sequence[_Any]]
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

    def to_dict(self, max_rows: int = 0) -> Dict[str, Sequence[_Any]]:
        """Create a dict representation of the translations."""
        records = self.records[:max_rows] if max_rows else self.records
        return {placeholder: [row[i] for row in records] for i, placeholder in enumerate(self.placeholders)}

    @staticmethod
    def to_dicts(
        source_translations: "SourcePlaceholderTranslations[SourceType]",
        max_rows: int = 0,
    ) -> Dict[SourceType, Dict[str, Sequence[_Any]]]:
        """Create a nested dict representation of the translations."""
        return {source: translations.to_dict(max_rows) for source, translations in source_translations.items()}

    @classmethod
    def from_dataframe(cls, source: SourceType, data: pd.DataFrame) -> "PlaceholderTranslations[SourceType]":
        """Create instance from a pandas DataFrame."""
        return cls(
            source,
            placeholders=tuple(data),
            records=data.values.tolist(),
            id_pos=data.columns.get_loc(ID) if ID in data else -1,
        )

    @classmethod
    def from_dict(cls, source: SourceType, data: Dict[str, Sequence[_Any]]) -> "PlaceholderTranslations[SourceType]":
        """Create instance from a dict."""
        return cls.from_dataframe(source, pd.DataFrame.from_dict(data))


SourcePlaceholderTranslations = Dict[SourceType, PlaceholderTranslations[SourceType]]
