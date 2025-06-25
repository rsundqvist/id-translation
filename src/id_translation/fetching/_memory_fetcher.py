from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Unpack

from ..offline.types import PlaceholderTranslations, SourcePlaceholderTranslations
from ..translator_typing import AbstractFetcherParams
from ..types import ID, IdType, SourceType
from ._abstract_fetcher import AbstractFetcher
from .types import FetchInstruction

if TYPE_CHECKING:
    import pandas


class MemoryFetcher(AbstractFetcher[SourceType, IdType]):
    """Fetch from memory.

    This is essentially a thin wrapper for the :class:`.PlaceholderTranslations` class.

    Args:
        data: A dict ``{source: PlaceholderTranslations}`` to fetch from.
        return_all: If ``False``, return only the requested IDs and placeholders.
        **kwargs: See :class:`.AbstractFetcher`.
    """

    def __init__(
        self,
        data: (
            SourcePlaceholderTranslations[SourceType]
            | Mapping[SourceType, PlaceholderTranslations[SourceType]]
            | Mapping[SourceType, "pandas.DataFrame"]
            | Mapping[SourceType, Mapping[str, Sequence[Any]]]
        ),
        return_all: bool = True,
        **kwargs: Unpack[AbstractFetcherParams[SourceType, IdType]],
    ) -> None:
        super().__init__(**kwargs)
        self._data = {
            source: pht
            if isinstance(pht, PlaceholderTranslations)
            else PlaceholderTranslations[SourceType].make(source, pht)
            for source, pht in data.items()
        }
        self._return_all = return_all

    @property
    def return_all(self) -> bool:
        """If ``True``, :meth:`fetch_translations` will filter by ID."""
        return self._return_all

    def _initialize_sources(self, task_id: int) -> dict[SourceType, list[str]]:  # noqa: ARG002
        return {source: list(pht.placeholders) for source, pht in self._data.items()}

    def fetch_translations(self, instr: FetchInstruction[SourceType, IdType]) -> PlaceholderTranslations[SourceType]:
        ret = self._data[instr.source]

        if self.return_all:
            return ret

        placeholder_indices = [
            ret.placeholders.index(placeholder)
            for placeholder in instr.placeholders  # requested
            if placeholder in ret.placeholders  # available
        ]

        if instr.ids is None:
            records = tuple(tuple(record[i] for i in placeholder_indices) for record in ret.records)
        else:
            ids = set(instr.ids)
            records = tuple(
                tuple(record[i] for i in placeholder_indices)
                for record in ret.records
                if record[ret.id_pos] in ids  # crash on missing IDs
            )
        placeholders = tuple(ret.placeholders[i] for i in placeholder_indices)
        id_pos = placeholders.index(ID) if ID in placeholders else -1
        return PlaceholderTranslations(instr.source, placeholders, records, id_pos)

    def __str__(self) -> str:
        class NoSources:
            def __repr__(self) -> str:
                return "<no sources>"

        sources = self.sources if self.sources else NoSources()
        return_all = self.return_all
        return f"{type(self).__name__}({sources=}, {return_all=})"
