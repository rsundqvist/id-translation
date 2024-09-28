import pytest
from id_translation import Translator
from id_translation.fetching import AbstractFetcher
from id_translation.fetching.types import FetchInstruction
from id_translation.offline.types import PlaceholderTranslations

pytestmark = pytest.mark.parametrize("with_data", [True, False])


@pytest.mark.parametrize("name", [None, "dont-fetch-me"])
def test_failure(name, with_data):
    with pytest.raises(AssertionError):
        _run(name, with_data=with_data)


def test_one_allowed(with_data):
    assert _run("source-0", with_data=with_data) == {
        "source-0": {1: "1:name"},
    }


def test_two_allowed(with_data):
    assert _run(["source-0", "source-1"], with_data=with_data) == {
        "source-0": {1: "1:name"},
        "source-1": {1: "1:name"},
    }


def test_ignore(with_data):
    assert _run(with_data=with_data, ignore_names=["dont-fetch-me"]) == {
        "source-0": {1: "1:name"},
        "source-1": {1: "1:name"},
    }


def _run(names=None, *, with_data, ignore_names=None):
    fetcher = GoOfflineFetcher()
    translator: Translator[str, str, int] = Translator(fetcher)

    data = {"source-0": 1, "source-1": 1, "dont-fetch-me": 1} if with_data else None
    offline = translator.go_offline(data, names=names, ignore_names=ignore_names)
    return offline.cache.to_translations()


class GoOfflineFetcher(AbstractFetcher[str, int]):
    def _initialize_sources(self, _: int) -> dict[str, list[str]]:
        placeholders = ["id", "name"]
        return {"source-0": placeholders, "source-1": placeholders, "dont-fetch-me": placeholders}

    def fetch_translations(self, instr: FetchInstruction[str, int]) -> PlaceholderTranslations[str]:
        if instr.source == "dont-fetch-me":
            raise AssertionError(f"{instr=}")
        return PlaceholderTranslations.from_dict(instr.source, {1: "name"})
