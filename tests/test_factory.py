from typing import Any

import pytest

from id_translation import Translator
from id_translation.exceptions import ConfigurationError
from id_translation.factory import default_fetcher_factory
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
