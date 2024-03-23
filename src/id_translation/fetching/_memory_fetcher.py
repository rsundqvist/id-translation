from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from ..offline.types import PlaceholderTranslations, SourcePlaceholderTranslations
from ..types import ID, IdType, SourceType
from ._abstract_fetcher import AbstractFetcher
from .types import FetchInstruction


class MemoryFetcher(AbstractFetcher[SourceType, IdType]):
    """Fetch from memory.

    Args:
        data: A dict ``{source: PlaceholderTranslations}`` to fetch from.
        return_all: If ``False``, return only the requested IDs and placeholders.
    """

    def __init__(
        self,
        data: (
            SourcePlaceholderTranslations[SourceType]
            | dict[SourceType, PlaceholderTranslations[SourceType]]
            | dict[SourceType, pd.DataFrame]
            | Mapping[SourceType, Mapping[str, Sequence[Any]]]
            | None
        ) = None,
        return_all: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._data: SourcePlaceholderTranslations[SourceType] = (
            {} if not data else {source: PlaceholderTranslations.make(source, pht) for source, pht in data.items()}
        )
        self.return_all = return_all

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
            records = [[record[i] for i in placeholder_indices] for record in ret.records]
        else:
            ids = set(instr.ids)
            records = [
                [record[i] for i in placeholder_indices]
                for record in ret.records
                if record[ret.id_pos] in ids  # crash on missing IDs
            ]
        placeholders = tuple(ret.placeholders[i] for i in placeholder_indices)
        id_pos = placeholders.index(ID) if ID in placeholders else -1
        return PlaceholderTranslations(instr.source, placeholders, records, id_pos)
