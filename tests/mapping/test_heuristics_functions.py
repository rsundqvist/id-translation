import pytest

from id_translation.mapping import heuristic_functions as hf


@pytest.mark.parametrize(
    "value, expected_match",
    [
        ("human_id", "humans"),
        ("human", "humans"),
        ("animal", "animals"),
        ("animals_id", "animals"),
    ],
)
def test_like_database_table(value, expected_match):
    candidates = ["humans", "animals"]
    expected_pos = candidates.index(expected_match)

    new_value, new_candidates = hf.like_database_table(value, candidates, None)
    assert candidates == ["humans", "animals"]
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
    actual_value, actual_candidates = hf.value_fstring_alias("VALUE", list("abc"), None, fstring, kwarg="KWARG")
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
    args = ("VALUE", list("abc"), "context", "{context}")
    if expected_value is None:
        with pytest.raises(ValueError, match="does not contain {value}"):
            hf.value_fstring_alias(*args, for_value=for_value)
        return

    actual_value, actual_candidates = hf.value_fstring_alias(*args, for_value=for_value)
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
        with pytest.raises(ValueError, match="does not contain {candidate}"):
            hf.candidate_fstring_alias("VALUE", candidates, None, fstring, kwarg="KWARG")
        return

    actual_value, actual_candidates = hf.candidate_fstring_alias("VALUE", candidates, None, fstring, kwarg="KWARG")

    assert candidates == ["CAND0", "CAND1"]
    assert actual_value == "VALUE"
    assert list(actual_candidates) == expected_candidates
