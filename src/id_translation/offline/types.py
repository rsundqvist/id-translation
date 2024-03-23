"""Types used for offline translation."""

import dataclasses as _dataclasses
import typing as _t
from collections.abc import Sequence as _Sequence
from typing import TYPE_CHECKING

from .. import types as _tt

if TYPE_CHECKING:
    import pandas

    from ._format import Format

FormatType = _t.Union[str, "Format"]

PlaceholdersTuple = tuple[str, ...]
TranslatedIds = dict[_tt.IdType, str]  # {id: translation}

DictMakeTypes = dict[str, _Sequence[_t.Any]] | dict[_tt.IdTypes, str]


@_dataclasses.dataclass
class PlaceholderTranslations(_t.Generic[_tt.SourceType]):
    """Matrix of ID translation components returned by fetchers."""

    source: _tt.SourceType
    """Source from which translations were retrieved."""
    placeholders: PlaceholdersTuple
    """Names of placeholders in the order in which they appear in `records`."""
    records: _Sequence[_Sequence[_t.Any]]
    """Matrix of shape `N x M` where `N` is the number of IDs returned and `M` is the length of `placeholders`."""
    id_pos: int = -1
    """Position if the the ID placeholder in `placeholders`."""

    @classmethod
    def make(cls, source: _tt.SourceType, data: "MakeTypes[_tt.SourceType]") -> _t.Self:
        """Try to make in instance from arbitrary input data.

        Args:
            source: Source label for the translations.
            data: Some data to convert to a PlaceholderTranslations instance.

        Returns:
            A new PlaceholderTranslations instance.

        Raises:
            TypeError: If `data` cannot be converted.
        """
        import pandas as pd

        if isinstance(data, pd.DataFrame):
            return cls.from_dataframe(source, data)
        if isinstance(data, dict):
            return cls.from_dict(source, data)
        if isinstance(data, PlaceholderTranslations):
            return cls(**_dataclasses.asdict(data))

        raise TypeError(data)  # pragma: no cover

    def to_dict(self, max_rows: int = 0) -> dict[str, _Sequence[_t.Any]]:
        """Create a dict representation of the translations."""
        records = self.records[:max_rows] if max_rows else self.records
        return {placeholder: [row[i] for row in records] for i, placeholder in enumerate(self.placeholders)}

    @staticmethod
    def to_dicts(
        source_translations: "SourcePlaceholderTranslations[_tt.SourceType]",
        max_rows: int = 0,
    ) -> dict[_tt.SourceType, dict[str, _Sequence[_t.Any]]]:
        """Create a nested dict representation of the translations."""
        return {source: translations.to_dict(max_rows) for source, translations in source_translations.items()}

    @classmethod
    def from_dataframe(cls, source: _tt.SourceType, data: "pandas.DataFrame") -> _t.Self:
        """Create instance from a pandas DataFrame."""
        return cls(
            source,
            placeholders=tuple(data),
            records=data.to_numpy().tolist(),
            id_pos=data.columns.get_loc(_tt.ID) if _tt.ID in data else -1,
        )

    @classmethod
    def from_dict(cls, source: _tt.SourceType, data: DictMakeTypes) -> _t.Self:
        """Create instance from a dict."""
        import pandas as pd

        if cls._is_simple_form(data):
            # Users may pass dicts on the form {source: {id: name}}, where our data={id: name}.
            _t.assert_type(data, dict[_tt.IdTypes, str])
            data = {_tt.ID: list(data.keys()), "name": list(data.values())}  # type: ignore[assignment]

        return cls.from_dataframe(source, pd.DataFrame.from_dict(data))

    @classmethod
    def _is_simple_form(cls, data: DictMakeTypes) -> _t.TypeGuard[dict[_tt.IdTypes, str]]:
        id_types = _t.get_args(_tt.IdTypes)
        return all(isinstance(key, id_types) and isinstance(value, str) for key, value in data.items())


MakeTypes = _t.Union[PlaceholderTranslations[_tt.SourceType], "pandas.DataFrame", DictMakeTypes]
SourcePlaceholderTranslations = dict[_tt.SourceType, PlaceholderTranslations[_tt.SourceType]]
