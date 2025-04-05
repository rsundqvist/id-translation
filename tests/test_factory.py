from typing import Any

import pytest

from id_translation import Translator
from id_translation.exceptions import ConfigurationError
from id_translation.fetching import AbstractFetcher, CacheAccess, MemoryFetcher, MultiFetcher
from id_translation.toml.factories._fetcher import default_fetcher_factory
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
    expected_type: type[AbstractFetcher[Any, Any]],
) -> None:
    fetcher: AbstractFetcher[str, int] = default_fetcher_factory(clazz, dict(data={}))
    assert isinstance(fetcher, expected_type)


def test_missing_config():
    path = ROOT.joinpath("bad-config.toml")
    with pytest.raises(ConfigurationError) as e:
        Translator.from_config(path)
    assert str(path) in str(e.value)


class TestEnvVars:
    @pytest.mark.parametrize("value", [True, False])
    def test_set(self, tmp_path, monkeypatch, value):
        monkeypatch.setenv("VAR_NAME", str(value).lower())
        self.run(tmp_path, expected=value)

    def test_unset(self, tmp_path):
        self.run(tmp_path, expected=True)

    @staticmethod
    def run(tmp_path, expected):
        main = """
        [translator]
        enable_uuid_heuristics = ${VAR_NAME:true}
        """
        main_path = tmp_path / "main.toml"
        main_path.write_text(main, encoding="utf-8")

        fetcher = """
        [fetching.MemoryFetcher]
        return_all = ${VAR_NAME:true}
        """
        fetcher_path = tmp_path / "fetcher.toml"
        fetcher_path.write_text(fetcher, encoding="utf-8")

        translator: Translator[str, str, int]
        translator = Translator.from_config(main_path, extra_fetchers=[fetcher_path])
        assert translator.enable_uuid_heuristics is expected
        assert isinstance(translator.fetcher, MemoryFetcher)
        assert translator.fetcher.return_all is expected


class TestCacheAccess:
    def test_does_not_inherit(self, tmp_path):
        cache = f"""
        type = "{__name__}.{BadCacheAccess.__name__}"
        """

        with pytest.raises(ConfigurationError, match="TypeError: Expected a subclass of CacheAccess"):
            self.create(tmp_path, cache)

    def test_only_one_cached(self, tmp_path):
        from id_translation.fetching._abstract_fetcher import _NOOP_CACHE_ACCESS
        from id_translation.fetching.exceptions import CacheAccessNotAvailableError

        cache = f"""
        type = "{__name__}.{DummyCacheAccess.__name__}"
        ttl = 3600
        """
        translator = self.create(tmp_path, cache)

        # Only check correct initialization. Behavioural tests in test_abstract_fetcher.py
        assert isinstance(translator.fetcher, MultiFetcher)
        fetcher_people, fetcher_animals = translator.fetcher.children

        # People fetcher - should be cached
        assert isinstance(fetcher_people, AbstractFetcher)
        assert isinstance(fetcher_people.cache_access, DummyCacheAccess)
        assert fetcher_people.cache_access.ttl == 3600

        # Animals fetcher - not cached
        assert isinstance(fetcher_animals, AbstractFetcher)
        assert fetcher_animals._cache_access is _NOOP_CACHE_ACCESS
        with pytest.raises(CacheAccessNotAvailableError, match="documentation/examples/caching/caching.html"):
            _ = fetcher_animals.cache_access

    @staticmethod
    def create(tmp_path, cache):
        main = """
        [translator]

        [fetching.MemoryFetcher.data]
        people = { id = [1991, 1999], name = ["Richard", "Sofia"] }

        [fetching.cache]
        """

        main_path = tmp_path / "main.toml"
        main_path.write_text(main + cache, encoding="utf-8")

        fetcher = """
        [fetching.MemoryFetcher.data]
        animals = { id = [2021], name = ["Morris"] }
        """
        fetcher_path = tmp_path / "fetcher.toml"
        fetcher_path.write_text(fetcher, encoding="utf-8")

        return Translator[str, str, int].from_config(main_path, extra_fetchers=[fetcher_path])


class BadCacheAccess:
    pass


class DummyCacheAccess(CacheAccess[Any, Any]):
    def __init__(self, ttl):
        super().__init__()
        self.ttl = ttl

    def load(self, instr):
        raise NotImplementedError

    def store(self, instr, translations):
        raise NotImplementedError
