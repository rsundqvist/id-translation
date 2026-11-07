"""Placeholder overrides apply as configured for fetchers that return every column, such as ``MemoryFetcher``."""

import os
import subprocess
import sys

import pytest

from id_translation import Translator
from id_translation.fetching import MemoryFetcher
from id_translation.mapping import Mapper


def translate(data, overrides, fmt, ids):
    fetcher: MemoryFetcher[str, int] = MemoryFetcher(data, mapper=Mapper("equality", overrides=overrides))
    return Translator[str, str, int](fetcher, fmt=fmt).translate(ids, names="people")


def test_swapped_overrides_swap():
    data = {"people": {"id": [1], "name": ["Alice"], "title": ["Dr"]}}
    assert translate(data, {"name": "title", "title": "name"}, "{id}:{name}/{title}", [1]) == ["1:Dr/Alice"]


def test_id_override_beats_a_literal_id_column():
    data = {"people": {"id": [1], "code": [7], "name": ["x"]}}
    assert translate(data, {"id": "code"}, "{id}:{name}", [7]) == ["7:x"]


def test_names_sharing_a_column_all_map():
    data = {"people": {"code": [1], "other": ["o"]}}
    assert translate(data, {"id": "code", "name": "code"}, "{id}:{name}", [1]) == ["1:1"]


def test_names_sharing_a_column_do_not_depend_on_the_hash_seed():
    script = (
        "from id_translation import Translator; from id_translation.fetching import MemoryFetcher;"
        " from id_translation.mapping import Mapper;"
        " f = MemoryFetcher({'people': {'code': [1], 'other': ['o']}},"
        " mapper=Mapper('equality', overrides={'name': 'code', 'id': 'code'}));"
        " print(Translator(f, fmt='{id}:{name}').translate([1], names='people'))"
    )
    for seed in ["1", "2", "3"]:
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=True)  # noqa: S603
        assert out.stdout.strip() == "['1:1']", f"{seed=}"


@pytest.mark.parametrize("overrides", [{"name": "title", "title": "name"}, {"id": "code"}])
def test_fetcher_data_is_not_renamed(overrides):
    data = {"people": {"id": [1], "code": [7], "name": ["Alice"], "title": ["Dr"]}}
    fetcher: MemoryFetcher[str, int] = MemoryFetcher(data, mapper=Mapper("equality", overrides=overrides))
    before = {source: pht.placeholders for source, pht in fetcher._data.items()}

    Translator[str, str, int](fetcher, fmt="{id}:{name}").translate([1, 7], names="people")

    assert {source: pht.placeholders for source, pht in fetcher._data.items()} == before
