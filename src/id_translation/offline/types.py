"""Types used for offline translation."""

import dataclasses as _dataclasses
import typing as _t
from collections.abc import Iterable as _Iterable
from collections.abc import Mapping as _Mapping
from collections.abc import Sequence as _Sequence

from .. import types as _tt
from .._utils import add_hints as _add_hints
from ..exceptions import MissingIdPlaceholderError as _MissingIdPlaceholderError

if _t.TYPE_CHECKING:
    import pandas

    from ._format import Format

FormatType = _t.Union[str, "Format"]

PlaceholdersTuple = tuple[str, ...]
PlaceholderAttributes = dict[str, set[str]]
TranslatedIds = dict[_tt.IdType, str]  # {id: translation}

DictMakeTypes = _t.Mapping[str, _Sequence[_t.Any]] | _t.Mapping[_tt.IdType, str]


@_dataclasses.dataclass(frozen=True)
class PlaceholderTranslations(_t.Generic[_tt.SourceType]):
    """Matrix of ID translation components returned by fetchers.

    Once placeholder names have been mapped back from the source's own names, one placeholder must be ``id``. A
    :class:`~id_translation.offline.TranslationMap` built from an instance without one raises
    :class:`~id_translation.exceptions.MissingIdPlaceholderError`.
    """

    source: _tt.SourceType
    """Source from which translations were retrieved."""
    placeholders: PlaceholdersTuple
    """Names of placeholders in the order in which they appear in `records`."""
    records: _Sequence[_Sequence[_t.Any]]
    """Matrix of shape `N x M` where `N` is the number of IDs returned and `M` is the length of `placeholders`."""
    placeholder_aliases: _Mapping[str, str] = _dataclasses.field(default_factory=dict, kw_only=True)
    """Alternative :attr:`placeholder <id_translation.offline.types.PlaceholderTranslations.placeholders>` names.

    Given as ``{alias: placeholder}``. After fetching, the aliases are the source's own names for the placeholders, e.g.
    ``{'code': 'id'}`` when ``id`` was mapped to a ``code`` column, or another wanted name for the same column. A
    placeholder always wins over a same-named alias.
    """

    @classmethod
    def make(cls, source: _tt.SourceType, data: "MakeTypes[_tt.SourceType, _tt.IdTypes]") -> _t.Self:
        """Try to make an instance from arbitrary input data.

        Args:
            source: Source label for the translations.
            data: Some data to convert to a ``PlaceholderTranslations`` instance.

        Returns:
            A :class:`~id_translation.offline.types.PlaceholderTranslations` instance.

        Raises:
            TypeError: If `data` cannot be converted.
            ValueError: If `data` is a dict of columns that differ in length.
        """
        if isinstance(data, PlaceholderTranslations):
            if isinstance(data, cls):
                return data  # Frozen and never mutated in place, so an offline Translator.copy() shares the records.
            return cls(data.source, data.placeholders, data.records, placeholder_aliases=data.placeholder_aliases)
        if isinstance(data, _Mapping):
            return cls.from_dict(source, data)

        try:
            from pandas import DataFrame  # noqa: PLC0415

            if isinstance(data, DataFrame):
                return cls.from_dataframe(source, data)
        except ImportError:
            pass

        raise TypeError(data)  # pragma: no cover

    def to_dict(self, max_rows: int = 0) -> dict[str, _Sequence[_t.Any]]:
        """Create a dict representation of the translations."""
        records = self.records[:max_rows] if max_rows else self.records
        return {placeholder: [row[i] for row in records] for i, placeholder in enumerate(self.placeholders)}

    def to_pandas(self, max_rows: int = 0) -> "pandas.DataFrame":
        """Create a pandas DataFrame representation of the translations."""
        from pandas import DataFrame  # noqa: PLC0415

        return DataFrame.from_dict(self.to_dict(max_rows))

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
        )

    @classmethod
    def from_dict(cls, source: _tt.SourceType, data: DictMakeTypes[_tt.IdType]) -> _t.Self:
        """Create instance from a dict."""
        is_name = [isinstance(value, str) for value in data.values()]
        if all(is_name):
            # Users may pass dicts on the form {source: {id: name}}, where our data={id: name}.
            records = tuple(tuple(item) for item in data.items())
            return cls(source, (_tt.ID, "name"), records)

        is_column = [
            isinstance(value, _Iterable) and not name for value, name in zip(data.values(), is_name, strict=True)
        ]
        if not all(is_column):
            # Blame the keys that break the form most values have.
            expected = is_column if sum(is_column) >= sum(is_name) else is_name
            keys = [key for key, ok in zip(data, expected, strict=True) if not ok]
            exc = TypeError(f"Cannot read data for {source=}: unexpected values for keys {keys}.")
            _add_hints(exc, "Pass either {id: name} with str names, or {placeholder: [values...]}.")
            raise exc

        placeholders: tuple[str, ...] = tuple(data)  # type: ignore[arg-type]
        columns = [list(column) for column in data.values()]
        lengths = {placeholder: len(column) for placeholder, column in zip(placeholders, columns, strict=True)}
        if len(set(lengths.values())) > 1:
            raise ValueError(f"Cannot read data for {source=}: columns differ in length: {lengths}.")
        records = tuple(zip(*columns, strict=True))
        return cls(source, placeholders, records)


MakeTypes = _t.Union[PlaceholderTranslations[_tt.SourceType], "pandas.DataFrame", DictMakeTypes[_tt.IdType]]
SourcePlaceholderTranslations = dict[_tt.SourceType, PlaceholderTranslations[_tt.SourceType]]


def _id_position(translations: PlaceholderTranslations[_t.Any]) -> int:
    try:
        return translations.placeholders.index(_tt.ID)
    except ValueError:
        pass

    raise _MissingIdPlaceholderError(
        f"Source {translations.source!r} has no {_tt.ID!r} placeholder: {sorted(translations.placeholders)}.",
        source=translations.source,
        placeholders=translations.placeholders,
        hints=(
            f"Inline data and plain Fetcher results are not mapped; the ID column must be named {_tt.ID!r}.",
            "To map another column, use a MemoryFetcher with an override:"
            f" Mapper(overrides={{{_tt.ID!r}: '<column>'}}).",
        ),
    )
