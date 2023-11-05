"""Test implementations."""
from typing import Any as _Any, Collection, Dict, Iterable, List, Tuple

import pandas as pd

from .fetching import Fetcher as _Fetcher
from .fetching.types import IdsToFetch as _IdsToFetch
from .mapping import DirectionalMapping as _DirectionalMapping, Mapper as _Mapper
from .mapping.types import ContextType, UserOverrideFunction, ValueType
from .offline.types import (
    PlaceholderTranslations as _PlaceholderTranslations,
    SourcePlaceholderTranslations as _SourcePlaceholderTranslations,
)
from .types import IdType, SourceType


class TestMapper(_Mapper[ValueType, ValueType, ContextType]):
    """Dummy ``Mapper`` implementation."""

    def apply(
        self,
        values: Iterable[ValueType],
        candidates: Iterable[ValueType],
        context: ContextType = None,
        override_function: UserOverrideFunction[ValueType, ValueType, ContextType] = None,
        **kwargs: _Any,
    ) -> _DirectionalMapping[ValueType, ValueType]:
        """Map values to themselves, unless `override_function` is given."""
        values = set(values)

        left_to_right: Dict[ValueType, Tuple[ValueType, ...]] = {v: (v,) for v in values}

        if override_function:
            candidates = set(candidates)
            for v in values:
                user_override = override_function(v, candidates, context)
                if user_override is not None:
                    left_to_right[v] = (user_override,)

        return _DirectionalMapping(left_to_right=left_to_right)


class TestFetcher(_Fetcher[SourceType, IdType]):
    """Dummy ``Fetcher`` implementation.

    A "happy path" fetcher implementation for testing purposes. Returns generated names for all IDs and placeholders,
    so translation retrieval will never fail when using this fetcher.
    """

    def __init__(self, sources: Collection[SourceType] = None) -> None:
        self._sources = set(sources or [])

    @property
    def allow_fetch_all(self) -> bool:
        return False  # pragma: no cover

    @property
    def online(self) -> bool:
        return False  # pragma: no cover

    @property
    def placeholders(self) -> Dict[SourceType, List[str]]:
        return {source: [] for source in self._sources}

    def copy(self) -> "TestFetcher[SourceType, IdType]":
        return type(self)(self.sources)

    def fetch(
        self,
        ids_to_fetch: Iterable[_IdsToFetch[SourceType, IdType]],
        placeholders: Iterable[str] = (),
        *,
        required: Iterable[str] = (),
        task_id: int = None,
        enable_uuid_heuristics: bool = False,
    ) -> _SourcePlaceholderTranslations[SourceType]:
        """Return generated translations for all IDs and placeholders."""
        return {itf.source: self._generate_data(itf, list(placeholders)) for itf in ids_to_fetch}

    @staticmethod
    def _generate_data(
        itf: _IdsToFetch[SourceType, IdType], placeholders: List[str]
    ) -> _PlaceholderTranslations[SourceType]:
        if itf.ids is None:
            raise NotImplementedError

        ids = list(itf.ids)
        df = pd.DataFrame([[f"{p}-of-{idx}" for p in placeholders] for idx in ids], columns=placeholders)
        df["id"] = ids
        return _PlaceholderTranslations.make(itf.source, df)

    def fetch_all(
        self,
        placeholders: Iterable[str] = (),
        *,
        required: Iterable[str] = (),
        task_id: int = None,
        enable_uuid_heuristics: bool = False,
    ) -> _SourcePlaceholderTranslations[SourceType]:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"TestFetcher(sources={repr(self._sources or None)})"

    def initialize_sources(self, task_id: int = -1, *, force: bool = False) -> None:
        pass
