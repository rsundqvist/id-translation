from uuid import UUID

import pytest

from id_translation import Translator
from id_translation.fetching import MemoryFetcher, MultiFetcher
from id_translation.fetching.types import FetchInstruction, IdsToFetch
from id_translation.mapping import Mapper
from id_translation.offline.types import PlaceholderTranslations


def test_unfiltered(data):
    actual = fetch_translations(data, return_all=True)
    assert actual == PlaceholderTranslations(
        source="humans",
        placeholders=("id", "name", "gender"),
        records=[[1991, "Richard", "Male"], [1999, "Sofia", "Female"]],
        id_pos=0,
    )


def test_filtered(data):
    actual = fetch_translations(data, return_all=False)
    assert actual == PlaceholderTranslations(source="humans", placeholders=("name",), records=(("Sofia",),), id_pos=-1)


def fetch_translations(data, return_all):
    fetcher: MemoryFetcher[str, int] = MemoryFetcher(data, return_all=return_all)
    instr = FetchInstruction(
        "humans",
        placeholders=("name",),
        required=set(),
        placeholder_attributes={},
        ids={1999},
        task_id=-1,
        enable_uuid_heuristics=False,
    )

    return fetcher.fetch_translations(instr)


@pytest.mark.parametrize("return_all", [False, True])
def test_mapped_id_column(return_all):
    # The ID column is found through the mapper, not by the literal name 'id'. With return_all=False the fetcher filters
    # on it; it used to filter on the last column instead, so nothing survived or the wrong records did.
    fetcher: MemoryFetcher[str, str] = MemoryFetcher(
        {"countries": {"code": ["US", "SE", "NO"], "name": ["USA", "Sweden", "Norway"]}},
        return_all=return_all,
        mapper=Mapper(overrides={"id": "code"}),
    )

    actual = fetcher.fetch([IdsToFetch("countries", {"US", "SE"})], placeholders=("name",))["countries"]

    assert actual.placeholders == ("id", "name")
    expected = {"US": "USA", "SE": "Sweden"}
    if return_all:
        expected["NO"] = "Norway"
    columns = actual.to_dict()
    assert dict(zip(columns["id"], columns["name"], strict=True)) == expected


_UUID = UUID("550e8400-e29b-41d4-a716-446655440000")
_UUID_FORMS = [_UUID, str(_UUID), str(_UUID).upper(), _UUID.hex]


@pytest.mark.parametrize("source_id", _UUID_FORMS, ids=repr)
@pytest.mark.parametrize("data_id", _UUID_FORMS, ids=repr)
def test_uuid_heuristics_filtered(source_id, data_id):
    fetcher: MemoryFetcher[str, str | UUID] = MemoryFetcher(
        {"s": {"id": [source_id], "name": ["found"]}}, return_all=False
    )
    translator: Translator[str, str, str | UUID] = Translator(fetcher, fmt="{name}", enable_uuid_heuristics=True)
    assert translator.translate([data_id], names="s") == ["found"]


def test_uuid_heuristics_with_ids_that_are_not_all_uuid_like():
    u = str(UUID(int=7))
    fetcher: MemoryFetcher[str, str] = MemoryFetcher({"s": {u: "uuid", "x": "ex"}}, return_all=False)
    translator: Translator[str, str, str] = Translator(fetcher, fmt="{name}", enable_uuid_heuristics=True)
    assert translator.translate([u, "x"], names="s") == ["uuid", "ex"]


def test_ready_made_translations_take_the_source_name():
    pht = PlaceholderTranslations("old", ("id", "name"), [(1, "a")], id_pos=0)
    fetcher: MemoryFetcher[str, int] = MemoryFetcher({"new": pht})
    assert fetcher.fetch_all()["new"].source == "new"

    multi = MultiFetcher(fetcher, MemoryFetcher({"other": {1: "x"}}))
    assert Translator[str, str, int](multi, fmt="{name}").translate([1], names="new") == ["a"]
