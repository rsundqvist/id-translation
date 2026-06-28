"""Test that placeholder attributes are properly forwarded by the AbstractFetcher.

This isn't used by any of the bundled implementation, but e.g. ORM fetchers with
lazy-loaded models may require this information.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import pandas as pd
import pytest

from id_translation import Translator
from id_translation.fetching import MemoryFetcher
from id_translation.mapping import Mapper
from id_translation.offline.types import PlaceholderAttributes

if TYPE_CHECKING:
    from id_translation.fetching.types import FetchInstruction

Id = int | str


def test_default(df, translator):
    df = translator.translate(df)
    assert df.to_numpy().tolist() == [
        ["49:Germany", "BER:Berlin", "de:German"],
        ["43:Austria", "VIE:Vienna", "de:German"],
        ["33:France", "CDG:Paris", "fr:French"],
    ]
    validate_instructions(
        translator,
        expected={"Capital": {}, "Country": {}, "Language": {}},
    )


def test_attr(df, translator):
    df = translator.translate(df[["Country"]], fmt="{name} (+{obj.code}): {obj.language.code}")
    assert df.to_numpy().tolist() == [
        ["Germany (+49): de"],
        ["Austria (+43): de"],
        ["France (+33): fr"],
    ]
    validate_instructions(
        translator,
        expected={"Country": {"obj": {"code", "language.code"}}},
    )


def test_alias(df, translator):
    translator = translator.copy(
        fmt=(
            "{obj.capital.name} "  # Nested object access.
            "({alias.capital.code}, {obj.capital.code}), "  # Same object under different names (Mapper config).
            "{name}"  # Plain non-object access.
            " ({obj.language.code})"
        ),
    )

    # Validate that the Format itself behaves correctly given the information it has access to.
    assert translator.fmt.placeholders == ("obj", "alias", "obj", "name", "obj")
    assert translator.fmt.required_placeholders == ("obj", "alias", "obj", "name", "obj")
    assert translator.fmt.placeholder_attributes == {
        "alias": {"capital.code"},  # Merged into 'obj' key by fetching process (see validate_instructions).
        "obj": {"capital.name", "language.code", "capital.code"},
    }

    # Validate the actual translation.
    assert translator.translate(df[["Country"]]).to_numpy().tolist() == [
        ["Berlin (BER, BER), Germany (de)"],
        ["Vienna (VIE, VIE), Austria (de)"],
        ["Paris (CDG, CDG), France (fr)"],
    ]

    # Validate that the attributes are merged correctly by the AbstractFetcher.
    validate_instructions(
        translator,
        expected={"Country": {"obj": {"language.code", "capital.code", "capital.name"}}},
    )


def test_alias_before_actual_merges_attributes(df, translator):
    """ai/codex: Found by AI review."""
    translator = translator.copy(fmt="{alias.capital.code}: {obj.language.code}")

    assert translator.translate(df[["Country"]]).to_numpy().tolist() == [
        ["BER: de"],
        ["VIE: de"],
        ["CDG: fr"],
    ]

    validate_instructions(
        translator,
        expected={"Country": {"obj": {"capital.code", "language.code"}}},
    )


def test_indexing(df, translator):
    translator = translator.copy(fmt="{id}:{name}: {alias.countries[0].name} ({obj.countries[0].capital.name})")

    assert translator.translate(df[["Language"]]).to_numpy().tolist() == [
        ["de:German: Germany (Berlin)"],
        ["de:German: Germany (Berlin)"],
        ["fr:French: France (Paris)"],
    ]

    validate_instructions(
        translator,
        expected={"Language": {"obj": {"countries[0].name", "countries[0].capital.name"}}},
    )


def test_legacy_fetcher_without_placeholder_attributes_warns():
    """A custom Fetcher predating `placeholder_attributes` should warn, not crash with a TypeError."""
    fetcher = _LegacyMemoryFetcher({"people": {"id": [1, 2], "name": ["Alice", "Bob"]}})
    translator = Translator[str, str, int](fetcher, fmt="{id}:{name}")

    with pytest.warns(FutureWarning, match="placeholder_attributes"):
        assert translator.translate([1, 2], names="people") == ["1:Alice", "2:Bob"]


@pytest.fixture
def translator() -> Translator[str, str, Id]:
    # Languages
    german = Language(name="German", code="de")
    french = Language(name="French", code="fr")
    languages = [german, french]

    # Countries
    germany = Country(name="Germany", code=49, language=german, capital=Capital(name="Berlin", code="BER"))
    austria = Country(name="Austria", code=43, language=german, capital=Capital(name="Vienna", code="VIE"))
    france = Country(name="France", code=33, language=french, capital=Capital(name="Paris", code="CDG"))
    countries = [germany, austria, france]
    capitals = [c.capital for c in countries]

    # Backfill
    for country in [germany, austria, france]:
        country.capital.country = country
    german.countries = [germany, austria]
    french.countries = [france]

    def _make(*objs: "P") -> tuple[str, pd.DataFrame]:
        records = [{"id": obj.code, "name": obj.name, "obj": obj} for obj in objs]
        return objs[0].__class__.__name__, pd.DataFrame(records)

    fetcher = InterceptFetcher(
        data=dict([_make(*countries), _make(*capitals), _make(*languages)]),
        mapper=Mapper(overrides={"alias": "obj"}),
    )
    return Translator[str, str, Id](fetcher)


@pytest.fixture
def df():
    data = {
        Country.__name__: [49, 43, 33],
        Capital.__name__: ["BER", "VIE", "CDG"],
        Language.__name__: ["de", "de", "fr"],
    }
    return pd.DataFrame(data)


def validate_instructions(translator: Translator[str, str, Id], expected: dict[str, PlaceholderAttributes]) -> None:
    fetcher = translator.fetcher
    assert isinstance(fetcher, InterceptFetcher)
    actual = {source: instr.placeholder_attributes for source, instr in fetcher.instr.items()}
    assert actual == expected


class InterceptFetcher(MemoryFetcher[str, Id]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instr: dict[str, FetchInstruction[str, Id]] = {}

    def fetch_translations(self, instr):
        assert instr.source not in self.instr
        self.instr[instr.source] = instr
        return super().fetch_translations(instr)


class _LegacyMemoryFetcher(MemoryFetcher[str, int]):
    """Custom fetcher with pre-`placeholder_attributes` ``fetch``/``fetch_all`` signatures (the v1.2.1 interface)."""

    def fetch(  # type: ignore[override]
        self, ids_to_fetch, placeholders=(), *, required=(), task_id=None, enable_uuid_heuristics=False
    ):
        return super().fetch(
            ids_to_fetch,
            placeholders,
            required=required,
            task_id=task_id,
            enable_uuid_heuristics=enable_uuid_heuristics,
        )

    def fetch_all(  # type: ignore[override]
        self, placeholders=(), *, required=(), sources=None, task_id=None, enable_uuid_heuristics=False
    ):
        return super().fetch_all(
            placeholders,
            required=required,
            sources=sources,
            task_id=task_id,
            enable_uuid_heuristics=enable_uuid_heuristics,
        )


class P(Protocol):
    name: str
    code: Id


@dataclass
class Language(P):
    name: str
    code: str  # ISO
    countries: list["Country"] = field(init=False)


@dataclass
class Capital(P):
    name: str
    code: str  # IATA
    country: "Country" = field(init=False)


@dataclass
class Country(P):
    name: str
    code: int  # ITU
    language: Language
    capital: Capital
