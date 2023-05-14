from typing import Any, Type

import pytest

from id_translation import Translator
from id_translation.factory import TranslatorFactory, _ConfigurationErrorWithFile, default_fetcher_factory
from id_translation.fetching import AbstractFetcher, MemoryFetcher
from id_translation.types import IdType, SourceType

from .conftest import ROOT


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


@pytest.mark.parametrize(
    "clazz",
    [
        None,
        "id_translation.Translator",
        "id_translation._translator.Translator",
        Translator,
    ],
)
def test_resolve_class(clazz):
    assert TranslatorFactory.resolve_class(clazz) == Translator


def test_missing_config():
    with pytest.raises(_ConfigurationErrorWithFile) as e:
        Translator.from_config(ROOT.joinpath("bad-config.toml"))
    assert "bad-config.toml" in str(e.value)
