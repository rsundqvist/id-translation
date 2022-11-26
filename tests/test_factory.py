from typing import Any, Optional, Type

import pytest

from id_translation import Translator
from id_translation.factory import TranslatorFactory, default_fetcher_factory
from id_translation.fetching import AbstractFetcher, MemoryFetcher
from id_translation.ttypes import IdType, SourceType


class AnotherFetcherType(MemoryFetcher[SourceType, IdType]):
    pass


@pytest.mark.parametrize(
    "clazz, expected_type",
    [
        ("MemoryFetcher", MemoryFetcher),
        ("id_translation.fetching.MemoryFetcher", MemoryFetcher),
        ("tests.test_factory.AnotherFetcherType", AnotherFetcherType),
    ],
)
def test_default_fetcher_factory(
    clazz: str,
    expected_type: Type[AbstractFetcher[Any, Any]],
) -> None:
    fetcher: AbstractFetcher[str, int] = default_fetcher_factory(clazz, dict(data={}))
    assert isinstance(fetcher, expected_type)


@pytest.mark.parametrize("arg", [None, "id_translation.Translator", "id_translation._translator.Translator"])
def test_resolve_class(arg: Optional[Type[Translator[Any, Any, Any]]]) -> None:
    assert TranslatorFactory.resolve_class(arg) == Translator
