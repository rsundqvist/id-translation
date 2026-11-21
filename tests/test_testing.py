from typing import Any

import pytest

from id_translation.fetching import Fetcher, MultiFetcher
from id_translation.fetching.types import IdsToFetch
from id_translation.testing import TestFetcher as _TestFetcher  # Aliased: pytest collects Test* classes


@pytest.mark.parametrize("multi", [False, True])
def test_fetch_returns_required(multi):
    fetcher: Fetcher[str, int] = _TestFetcher(["people"])
    if multi:
        fetcher = MultiFetcher(fetcher)

    actual = fetcher.fetch([IdsToFetch("people", {1})], ("name",), required=iter(["title"]))["people"]

    assert set(actual.placeholders) == {"id", "name", "title"}


@pytest.mark.parametrize("seed", ["0", "1"])
def test_fetcherless_translator_keeps_the_order(seed, monkeypatch, tmp_path):
    from .conftest import run_python

    monkeypatch.setenv("PYTHONHASHSEED", seed)  # A set's iteration order changes with it.
    names = ["customer", "film", "category", "staff", "store"]
    code = f"""from id_translation import Translator
print(list(Translator().map(dict.fromkeys({names}))))
"""
    assert run_python("-c", code, cwd=tmp_path).strip() == str(names)


@pytest.mark.parametrize("seed", ["0", "1"])
def test_fetched_ids_are_in_a_fixed_order(seed, monkeypatch, tmp_path):
    from .conftest import run_python

    monkeypatch.setenv("PYTHONHASHSEED", seed)  # A set's iteration order changes with it.
    code = """from id_translation import Translator
translator = Translator()
print(translator.fetch({"people": ["d", "b", "e", "a", "c"]}).to_dicts()["people"]["id"])
print(translator.fetch({"mixed": [2, "b", 1, "a"]}).to_dicts()["mixed"]["id"])
"""
    assert run_python("-c", code, cwd=tmp_path).splitlines() == [
        "['a', 'b', 'c', 'd', 'e']",
        "['a', 'b', 1, 2]",  # By repr(), since int and str do not compare.
    ]


def test_fetch_ids_without_order_or_repr():
    class Id:
        def __str__(self) -> str:
            return "id"

        def __repr__(self) -> str:
            raise RuntimeError

    ids: set[Any] = {Id(), Id()}  # Not an IdType: int, str and UUID all order and repr.
    actual = _TestFetcher(["people"]).fetch([IdsToFetch("people", ids)], ("name",))["people"]

    assert set(actual.to_dict()["id"]) == ids


@pytest.mark.parametrize("seed", ["0", "1"])
def test_sources_keep_the_order(seed, monkeypatch, tmp_path):
    from .conftest import run_python

    monkeypatch.setenv("PYTHONHASHSEED", seed)  # A set's iteration order changes with it.
    sources = ["customer", "film", "category", "staff", "store"]
    code = f"""from id_translation.testing import TestFetcher
print(list(TestFetcher({sources}).sources))
"""
    assert run_python("-c", code, cwd=tmp_path).strip() == str(sources)
