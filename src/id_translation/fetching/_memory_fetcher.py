from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Unpack

from .. import _uuid_utils
from ..offline.types import PlaceholderTranslations, SourcePlaceholderTranslations
from ..types import IdType, SourceType
from ._abstract_fetcher import AbstractFetcher, AbstractFetcherParams, format_sources
from .types import FetchInstruction

if TYPE_CHECKING:
    import pandas


class MemoryFetcher(AbstractFetcher[SourceType, IdType]):
    """Fetch from memory.

    This is essentially a thin wrapper for the :class:`~id_translation.offline.types.PlaceholderTranslations` class.

    Args:
        data: A dict ``{source: data_for_source}``. Each per-source value may be anything accepted by
            :meth:`PlaceholderTranslations.make <id_translation.offline.types.PlaceholderTranslations.make>`:

            * ``{id: label}`` -- the simplest form; one label per ID.
            * ``{placeholder: [values, ...]}`` -- column-oriented; use this for multiple placeholders.
            * A :class:`pandas.DataFrame`.
            * A ready-made :class:`~id_translation.offline.types.PlaceholderTranslations`.

            The first two forms are plain dicts, so they may be written directly in TOML configuration as
            ``[fetching.MemoryFetcher.data.<source>]``-sections (see :ref:`translator-config-fetching`).
        return_all: If ``True``, return every ID and placeholder of a source instead of only the requested ones.
            Translations then include IDs that were not asked for, e.g. as extra categories when translating to a
            categorical ``dtype``.
        **kwargs: See :class:`~id_translation.fetching.AbstractFetcher`.

    Every source must have an ID column: :meth:`~id_translation.fetching.AbstractFetcher.initialize_sources` raises
    :class:`~id_translation.fetching.exceptions.UnknownIdPlaceholderError` for a source whose placeholders do not map
    to ``id``.
    """

    def __init__(
        self,
        data: (
            SourcePlaceholderTranslations[SourceType]
            | Mapping[SourceType, PlaceholderTranslations[SourceType]]
            | Mapping[SourceType, "pandas.DataFrame"]
            | Mapping[SourceType, Mapping[str, Sequence[Any]]]
        ),
        *,
        return_all: bool = False,
        **kwargs: Unpack[AbstractFetcherParams[SourceType, IdType]],
    ) -> None:
        super().__init__(**kwargs)
        self._data = {
            source: pht
            if isinstance(pht, PlaceholderTranslations)
            else PlaceholderTranslations[SourceType].make(source, pht)
            for source, pht in data.items()
        }
        # ID columns are resolved through the mapper in _initialize_sources() and kept here: the objects in `data` may
        # be the caller's, and another fetcher may map the same object differently.
        self._id_pos: dict[SourceType, int] = {}
        self._return_all = return_all

    @property
    def return_all(self) -> bool:
        """If ``True``, return all data instead of only the requested IDs and placeholders."""
        return self._return_all

    def _initialize_sources(self, task_id: int) -> dict[SourceType, list[str]]:
        for source, pht in self._data.items():
            id_column = self.id_column(source, candidates=pht.placeholders, task_id=task_id)
            if id_column is not None:  # initialize_sources() raises for the others.
                self._id_pos[source] = pht.placeholders.index(id_column)

        return {source: list(pht.placeholders) for source, pht in self._data.items()}

    def fetch_translations(self, instr: FetchInstruction[SourceType, IdType]) -> PlaceholderTranslations[SourceType]:
        """Fetch translations from memory."""
        ret = self._data[instr.source]

        if self.return_all:
            return ret

        id_pos = self._id_pos[instr.source]
        placeholder_indices = [
            ret.placeholders.index(placeholder)
            for placeholder in instr.placeholders  # requested
            if placeholder in ret.placeholders  # available
        ]

        if instr.ids is None:
            records = tuple(tuple(record[i] for i in placeholder_indices) for record in ret.records)
        else:
            ids = set(instr.ids)
            cast = _uuid_utils.try_cast_one if instr.enable_uuid_heuristics else _identity
            records = tuple(
                tuple(record[i] for i in placeholder_indices)
                for record in ret.records
                if cast(record[id_pos]) in ids  # crash on missing IDs
            )

        placeholders = tuple(ret.placeholders[i] for i in placeholder_indices)
        return PlaceholderTranslations(instr.source, placeholders, records)

    def __str__(self) -> str:
        return_all = self.return_all
        return f"{type(self).__name__}(sources={format_sources(self._placeholders)}, {return_all=})"


def _identity(idx: Any) -> Any:
    return idx
