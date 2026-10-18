from uuid import UUID

import pytest

from id_translation import Translator
from id_translation.fetching import MemoryFetcher
from id_translation.fetching.exceptions import UnknownIdPlaceholderError
from id_translation.fetching.types import FetchInstruction, IdsToFetch
from id_translation.mapping import Mapper
from id_translation.offline.types import PlaceholderTranslations


def test_unfiltered(data):
    actual = fetch_translations(data, return_all=True)
    assert actual == PlaceholderTranslations(
        source="humans",
        placeholders=("id", "name", "gender"),
        records=[[1991, "Richard", "Male"], [1999, "Sofia", "Female"]],
    )


def test_filtered(data):
    actual = fetch_translations(data, return_all=False)
    assert actual == PlaceholderTranslations(source="humans", placeholders=("name",), records=(("Sofia",),))


def fetch_translations(data, return_all):
    fetcher: MemoryFetcher[str, int] = MemoryFetcher(data, return_all=return_all)
    fetcher.initialize_sources()
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


def test_unmapped_id_column_raises_at_initialize_sources():
    # Nothing maps to 'id', so there is no column to filter on. Raise at the validation gate, not at first fetch.
    fetcher: MemoryFetcher[str, str] = MemoryFetcher({"lookup": {"key": ["a"], "name": ["A"]}})

    with pytest.raises(UnknownIdPlaceholderError, match=r"\['id'\] not recognized") as exc_info:
        fetcher.initialize_sources()
    assert exc_info.value.placeholders == ("key", "name")
    assert exc_info.value.source == "lookup"
    hint = "Hint: Rename the ID column of 'lookup' to 'id', or map 'id' to it with an override."
    assert exc_info.value.__notes__ == [hint]


def test_bad_id_override_raises_at_initialize_sources():
    fetcher: MemoryFetcher[str, str] = MemoryFetcher(
        {"lookup": {"key": ["a"], "name": ["A"]}}, mapper=Mapper(overrides={"id": "nope"})
    )

    with pytest.raises(UnknownIdPlaceholderError, match=r"\['nope'\] not recognized") as exc_info:
        fetcher.initialize_sources()
    assert (
        "Hint: The override 'id' -> 'nope' names a placeholder that 'lookup' does not have." in exc_info.value.__notes__
    )


def test_filtered_source_raises_at_initialize_sources():
    # filter_sources() rejects a source by rejecting its 'id'; a fetcher that still lists the source raises.
    mapper: Mapper[str, str, str] = Mapper(filter_functions=[("filter_sources", {"regex": "meta", "remove": True})])
    fetcher: MemoryFetcher[str, int] = MemoryFetcher({"meta": {"id": [1]}, "people": {"id": [1]}}, mapper=mapper)

    with pytest.raises(UnknownIdPlaceholderError, match=r"\['id'\] not recognized") as exc_info:
        fetcher.initialize_sources()
    assert exc_info.value.source == "meta"
    assert exc_info.value.__notes__ == ["Hint: A filter rejects the ID column of 'meta', but every source needs one."]


@pytest.mark.parametrize("return_all", [False, True])
def test_shared_data_is_not_mutated(return_all):
    # A PlaceholderTranslations passed in is stored as-is, so the mapper's answer is kept per fetcher: two fetchers
    # may map the same object differently, and the caller's object stays untouched.
    pht = PlaceholderTranslations.make("c", {"code": ["US", "SE"], "alt": ["SE", "US"], "name": ["USA", "Sweden"]})
    by_code: MemoryFetcher[str, str] = MemoryFetcher(
        {"c": pht}, mapper=Mapper(overrides={"id": "code"}), return_all=return_all
    )
    by_alt: MemoryFetcher[str, str] = MemoryFetcher(
        {"c": pht}, mapper=Mapper(overrides={"id": "alt"}), return_all=return_all
    )

    def fetch_us(fetcher):
        columns = fetcher.fetch([IdsToFetch("c", {"US"})], placeholders=("name",))["c"].to_dict()
        return dict(zip(columns["id"], columns["name"], strict=True))["US"]

    assert fetch_us(by_code) == "USA"
    assert fetch_us(by_alt) == "Sweden"
    assert fetch_us(by_code) == "USA"  # Unaffected by by_alt.
    assert pht.placeholders == ("code", "alt", "name")
    assert pht.placeholder_aliases == {}


_UUID = UUID("550e8400-e29b-41d4-a716-446655440000")
_UUID_FORMS = [_UUID, str(_UUID), str(_UUID).upper(), _UUID.hex]


@pytest.mark.parametrize("source_id", _UUID_FORMS, ids=repr)
@pytest.mark.parametrize("data_id", _UUID_FORMS, ids=repr)
def test_uuid_heuristics_filtered(source_id, data_id):
    fetcher: MemoryFetcher[str, str | UUID] = MemoryFetcher({"s": {"id": [source_id], "name": ["found"]}})
    translator: Translator[str, str, str | UUID] = Translator(fetcher, fmt="{name}", enable_uuid_heuristics=True)
    assert translator.translate([data_id], names="s") == ["found"]
