from pathlib import Path

import pytest

from id_translation.mapping import heuristic_functions as hf

SINGULAR_TO_PLURAL = map(str.split, Path(__file__).parent.joinpath("singular-to-plural.txt").read_text().splitlines())


@pytest.mark.parametrize(
    "value, expected_match",
    [
        ("human_id", "humans"),
        ("human", "humans"),
        ("animal", "animals"),
        ("animals_id", "animals"),
        ("country_id", "countries"),
        ("city_id", "cities"),
        ("language_id", "languages"),
        ("scratch_id", "scratches"),
        ("hash_id", "hashes"),
        ("hex_id", "hexes"),
    ],
)
def test_like_database_table(value, expected_match):
    candidates = ["humans", "animals", "countries", "cities", "languages", "scratches", "hashes", "hexes"]
    expected_pos = candidates.index(expected_match)

    new_value, new_candidates = hf.like_database_table(value, candidates, None)
    assert candidates == [
        "humans",
        "animals",
        "countries",
        "cities",
        "languages",
        "scratches",
        "hashes",
        "hexes",
    ], "input changed"
    assert new_value == new_candidates[expected_pos]


@pytest.mark.parametrize(
    "value, candidates, expect_match",
    [
        ("first_bite_victim", {"humans", "animals"}, True),
        ("second_bite_victim", {"humans", "animals"}, True),
        ("second_bite_victim", {"animals"}, False),
        ("bitten_by", ["humans", "animals"], False),
    ],
)
def test_short_circuit(value, candidates, expect_match):
    actual = hf.short_circuit(value, candidates, None, value_regex=".*_bite_victim$", target_candidate="humans")
    assert actual == ({"humans"} if expect_match else set())


@pytest.mark.parametrize(
    "fstring, expected_value",
    [
        ("{value}", "VALUE"),
        ("{value}_{kwarg}", "VALUE_KWARG"),
    ],
)
def test_value_fstring_alias(fstring, expected_value):
    actual_value, actual_candidates = hf.value_fstring_alias("VALUE", list("abc"), None, fstring=fstring, kwarg="KWARG")
    assert actual_value == expected_value
    assert actual_candidates == list("abc")


@pytest.mark.parametrize(
    "for_value, expected_value",
    [
        (None, None),
        ("VALUE", "context"),
        ("NOT_VALUE", "VALUE"),
    ],
)
def test_value_fstring_alias_for_value(for_value, expected_value):
    args = ("VALUE", list("abc"), "context")
    if expected_value is None:
        with pytest.raises(ValueError, match=r"does not contain {value}"):
            hf.value_fstring_alias(*args, fstring="{context}", for_value=for_value)
        return

    actual_value, actual_candidates = hf.value_fstring_alias(*args, fstring="{context}", for_value=for_value)
    assert actual_value == expected_value
    assert actual_candidates == list("abc")


@pytest.mark.parametrize(
    "fstring, expected_candidates",
    [
        ("{candidate}", ["CAND0", "CAND1"]),
        ("{candidate}_{kwarg}", ["CAND0_KWARG", "CAND1_KWARG"]),
        ("no-kwarg", None),
        ("only {kwarg}", None),
    ],
)
def test_candidate_fstring_alias(fstring, expected_candidates):
    candidates = ["CAND0", "CAND1"]

    if expected_candidates is None:
        with pytest.raises(ValueError, match=r"does not contain {candidate}"):
            hf.candidate_fstring_alias("VALUE", candidates, None, fstring=fstring, kwarg="KWARG")
        return

    actual_value, actual_candidates = hf.candidate_fstring_alias(
        "VALUE", candidates, None, fstring=fstring, kwarg="KWARG"
    )

    assert candidates == ["CAND0", "CAND1"]
    assert actual_value == "VALUE"
    assert list(actual_candidates) == expected_candidates


class TestNounTransformer:
    @pytest.mark.parametrize("singular, plural", SINGULAR_TO_PLURAL)
    def test_word_list(self, singular, plural):
        transformer = hf.NounTransformer()
        actual = transformer(plural)
        assert actual == singular, f"{plural=}"

    def test_cached(self, monkeypatch):
        monkeypatch.setattr(hf, "_NOUN_TRANSFORMER_CACHE", {})

        p2s = f"{__name__}.cached_transformer_instance"

        hf.smurf_columns("", ["1", "2"], "", plural_to_singular=p2s)
        assert self.CachedTransformer.total_call_count == 1

        hf.smurf_columns("", ["3"], "", plural_to_singular=p2s)
        assert self.CachedTransformer.total_call_count == 2

        assert len(hf._NOUN_TRANSFORMER_CACHE) == 1
        assert hf._NOUN_TRANSFORMER_CACHE[p2s] == cached_transformer_instance

    def test_callable(self, monkeypatch):
        monkeypatch.setattr(hf, "_NOUN_TRANSFORMER_CACHE", {})

        call_count = 0

        def p2s(s):
            nonlocal call_count
            call_count += 1
            return s

        hf.smurf_columns("", ["1", "2"], "", plural_to_singular=p2s)
        assert call_count == 1

        hf.smurf_columns("", ["3"], "", plural_to_singular=p2s)
        assert call_count == 2

        assert len(hf._NOUN_TRANSFORMER_CACHE) == 0

    def test_overrides_are_needed(self, monkeypatch):
        irregulars = hf.NounTransformer.IRREGULARS
        monkeypatch.setattr(hf.NounTransformer, "IRREGULARS", {})

        ns = hf.NounTransformer()
        for plural, singular in irregulars.items():
            assert singular != ns(plural)

    class CachedTransformer:
        total_call_count = 0

        def __call__(self, arg):
            TestNounTransformer.CachedTransformer.total_call_count += 1
            return arg


cached_transformer_instance = TestNounTransformer.CachedTransformer()
