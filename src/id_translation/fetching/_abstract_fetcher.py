import logging
from abc import abstractmethod
from time import perf_counter
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from rics.collections.dicts import InheritedKeysDict, reverse_dict
from rics.mapping import HeuristicScore, Mapper
from rics.mapping.score_functions import modified_hamming
from rics.misc import tname
from rics.performance import format_perf_counter

from id_translation.fetching import exceptions

from ..exceptions import ConnectionStatusError
from ..offline.types import PlaceholdersTuple, PlaceholderTranslations, SourcePlaceholderTranslations
from ..types import ID, IdType, SourceType
from ._fetcher import Fetcher
from .types import FetchInstruction, IdsToFetch

LOGGER = logging.getLogger(__package__).getChild("AbstractFetcher")


class AbstractFetcher(Fetcher[SourceType, IdType]):
    """Base class for retrieving translations from an external source.

    Args:
        mapper: A :class:`rics.mapping.Mapper` instance used to adapt placeholder names in sources to wanted names, ie
            the names of the placeholders that are in the translation :class:`.Format` being used.
        allow_fetch_all: If ``False``, an error will be raised when :meth:`fetch_all` is called.
    """

    _FETCH_ALL: str = "FETCH_ALL"

    def __init__(
        self,
        mapper: Mapper[str, str, SourceType] = None,
        allow_fetch_all: bool = True,
    ) -> None:
        self._mapper = mapper or Mapper(**self.default_mapper_kwargs())
        if not self.mapper.context_sensitive_overrides:  # pragma: no cover
            raise ValueError(f"Mapper must have context-sensitive overrides (type {InheritedKeysDict.__name__}).")

        self._mapping_cache: Dict[SourceType, Dict[str, Optional[str]]] = {}
        self._allow_fetch_all = allow_fetch_all

    def map_placeholders(
        self,
        source: SourceType,
        placeholders: Iterable[str],
        candidates: Iterable[str] = None,
        clear_cache: bool = False,
    ) -> Dict[str, Optional[str]]:
        """Map `placeholder` names to the actual names used in `source`.

        Args:
            source: The source to map placeholders for.
            placeholders: Desired :attr:`~.Format.placeholders`.
            candidates: A subset of candidates (placeholder names) in `source` to map with `placeholders`. ``None``
                =retrieve using :meth:`get_placeholders`.
            clear_cache: If ``True``, force a full remap.

        Returns:
            A dict ``{wanted_placeholder_name: actual_placeholder_name_in_source}``, where
            `actual_placeholder_name_in_source` will be ``None`` if the wanted placeholder could not be mapped to any of
            the candidates available for the source.
        """
        if clear_cache or source not in self._mapping_cache:
            self._mapping_cache[source] = {}
        ans = self._mapping_cache[source]

        candidates = set(self.get_placeholders(source) if candidates is None else candidates)
        placeholders = set(placeholders).difference(ans)  # Don't remap cached mappings

        for actual, wanted in self.mapper.apply(placeholders, candidates, context=source).left_to_right.items():
            ans[actual] = wanted[0]

        for not_mapped in placeholders.difference(ans):
            ans[not_mapped] = None

        return ans

    def id_column(self, source: SourceType, candidates: Iterable[str] = None) -> Optional[str]:
        """Return the ID column for `source`."""
        return self.map_placeholders(source, [ID], candidates=candidates)[ID]

    @property
    def mapper(self) -> Mapper[str, str, SourceType]:
        """Return the ``Mapper`` instance used for placeholder name mapping."""
        return self._mapper

    @property
    def online(self) -> bool:
        return True  # pragma: no cover

    def assert_online(self) -> None:
        """Raise an error if offline.

        Raises:
            ConnectionStatusError: If not online.
        """
        if not self.online:  # pragma: no cover
            raise ConnectionStatusError("disconnected")

    @property
    @abstractmethod
    def sources(self) -> List[SourceType]:
        raise NotImplementedError

    @property
    @abstractmethod
    def placeholders(self) -> Dict[SourceType, List[str]]:
        raise NotImplementedError

    def get_placeholders(self, source: SourceType) -> List[str]:
        """Get placeholders for `source`."""
        placeholders = self.placeholders
        if source not in placeholders:
            raise exceptions.UnknownSourceError({source}, self.sources)
        return placeholders[source]

    @property
    def allow_fetch_all(self) -> bool:
        return self._allow_fetch_all

    def fetch(
        self,
        ids_to_fetch: Iterable[IdsToFetch[SourceType, IdType]],
        placeholders: Iterable[str] = (),
        required: Iterable[str] = (),
    ) -> SourcePlaceholderTranslations[SourceType]:
        unknown_sources = set(t.source for t in ids_to_fetch).difference(self.sources)
        if unknown_sources:
            raise exceptions.UnknownSourceError(unknown_sources, self.sources)

        if not self.allow_fetch_all and any(t.ids is None for t in ids_to_fetch):  # pragma: no cover
            raise exceptions.ForbiddenOperationError(self._FETCH_ALL)

        return self._fetch(ids_to_fetch, tuple(placeholders), set(required))

    def fetch_all(
        self,
        placeholders: Iterable[str] = (),
        required: Iterable[str] = (),
    ) -> SourcePlaceholderTranslations[SourceType]:
        if not self.allow_fetch_all:
            raise exceptions.ForbiddenOperationError(self._FETCH_ALL)

        ids_to_fetch: List[IdsToFetch[SourceType, IdType]] = [IdsToFetch(source, None) for source in self.sources]
        return self._fetch(ids_to_fetch, tuple(placeholders), set(required))

    @abstractmethod
    def fetch_translations(
        self, instruction: FetchInstruction[SourceType, IdType]
    ) -> PlaceholderTranslations[SourceType]:
        """Retrieve placeholder translations from the source.

        Args:
            instruction: A single instruction for IDs to fetch. If IDs is ``None``, the fetcher should retrieve data for
                as many IDs as possible.

        Returns:
            Placeholder translation elements.

        Raises:
            UnknownPlaceholderError: If the placeholder is unknown to the fetcher.
        """

    def close(self) -> None:
        pass

    def _fetch(
        self,
        ids_to_fetch: Iterable[IdsToFetch[SourceType, IdType]],
        placeholders: PlaceholdersTuple,
        required_placeholders: Set[str],
    ) -> SourcePlaceholderTranslations[SourceType]:

        return {
            translations.source: translations
            for translations in self._fetch_translations(ids_to_fetch, placeholders, required_placeholders)
        }

    def _fetch_translations(
        self,
        ids_to_fetch: Iterable[IdsToFetch[SourceType, IdType]],
        placeholders: PlaceholdersTuple,
        required_placeholders: Set[str],
    ) -> Iterable[PlaceholderTranslations[SourceType]]:
        for itf in ids_to_fetch:
            reverse_mappings, instr = self._make_fetch_instruction(itf, placeholders, required_placeholders)

            start = perf_counter()
            translations = self.fetch_translations(instr)
            if LOGGER.isEnabledFor(logging.DEBUG):
                LOGGER.debug(
                    f"Fetched {translations.placeholders} for {len(translations.records)} IDS "
                    f"from '{translations.source}' in {format_perf_counter(start)} using {self}."
                )

            if reverse_mappings:
                # The mapping is only in reverse from the Fetchers point-of-view; we're mapping back to "proper" values.
                translations.placeholders = tuple(reverse_mappings.get(p, p) for p in translations.placeholders)

            translations.id_pos = translations.placeholders.index(ID)
            yield translations

    def _make_fetch_instruction(
        self,
        itf: IdsToFetch[SourceType, IdType],
        placeholders: PlaceholdersTuple,
        required_placeholders: Set[str],
    ) -> Tuple[Optional[Dict[str, str]], FetchInstruction[SourceType, IdType]]:
        fetch_all_placeholders = not placeholders

        required_placeholders.add(ID)
        if ID not in placeholders:
            placeholders = (ID,) + placeholders

        wanted_to_actual = self._make_mapping(itf, placeholders, required_placeholders)

        actual_to_wanted: Dict[str, str] = reverse_dict(wanted_to_actual)
        need_placeholder_mapping = actual_to_wanted != wanted_to_actual
        if need_placeholder_mapping:
            placeholders = tuple(map(wanted_to_actual.__getitem__, filter(wanted_to_actual.__contains__, placeholders)))
            required_placeholders = set(map(wanted_to_actual.__getitem__, required_placeholders))

        return (
            actual_to_wanted if need_placeholder_mapping else None,
            FetchInstruction(
                source=itf.source,
                ids=itf.ids,
                placeholders=placeholders,
                required=required_placeholders,
                all_placeholders=fetch_all_placeholders,
            ),
        )

    def _make_mapping(
        self, itf: IdsToFetch[SourceType, IdType], placeholders: PlaceholdersTuple, required_placeholders: Set[str]
    ) -> Dict[str, str]:
        wanted_to_actual = self.map_placeholders(itf.source, placeholders)
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug(f"Placeholder mappings for source={repr(itf.source)}: {wanted_to_actual}.")

        ans: Dict[str, str] = {wanted: actual for wanted, actual in wanted_to_actual.items() if actual}
        missing = required_placeholders.difference(ans)
        if missing:
            source = itf.source
            raise exceptions.UnknownPlaceholderError(
                f"Required placeholders {missing} not recognized."
                f" For {source=}, known placeholders are: {sorted(ans)} for {self}."
            )
        return ans

    @classmethod
    def default_mapper_kwargs(cls) -> Dict[str, Any]:
        """Return default ``Mapper`` arguments for ``AbstractFetcher`` implementations."""
        return dict(
            score_function=HeuristicScore(
                cls.default_score_function,  # type: ignore
                heuristics=[("force_lower_case", {})],
            ),
            overrides=InheritedKeysDict(),
        )

    @classmethod
    def default_score_function(cls, value: str, candidates: Iterable[str], context: str) -> Iterable[float]:
        """Compute score for candidates."""
        return modified_hamming(value, candidates, context)

    def __str__(self) -> str:
        sources = self.sources if self.sources else "<no sources>"
        return f"{tname(self)}({sources=})"
