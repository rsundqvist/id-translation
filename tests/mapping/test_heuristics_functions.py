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
    "value, candidates, expected",
    [
        ("target-miss", ["MATCH0", "MATCH1"], []),
        ("TARGET", ["wrong0", "wrong1"], []),
        ("TARGET", ["MATCH0", "wrong1"], ["MATCH0"]),
        ("TARGET", ["MATCH0", "wrong1", "MATCH1"], ["MATCH0", "MATCH1"]),
    ],
)
def test_short_circuit_to_value(value, candidates, expected):
    actual = sorted(list(hf.short_circuit_to_value(value, candidates, None, ".*MATCH.*", target="TARGET")))
    assert actual == expected


@pytest.mark.parametrize(
    "value, add_target, expected",
    [
        ("match", False, []),
        ("miss", True, []),
        ("match", True, ["TARGET"]),
    ],
)
def test_short_circuit_to_candidate(value, add_target, expected):
    candidates = ["cand"]
    if add_target:
        candidates.append("TARGET")
    actual = list(hf.short_circuit_to_candidate(value, candidates, None, ".*MATCH.*", target="TARGET"))
    assert actual == expected


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
