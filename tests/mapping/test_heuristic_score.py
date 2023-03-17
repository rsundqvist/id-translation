import pytest

from id_translation.mapping import HeuristicScore

inf = float("inf")


@pytest.fixture(scope="module")
def heuristic_score():
    return HeuristicScore(
        "equality",
        heuristics=[
            ("force_lower_case", dict(mutate=True)),
            ("short_circuit_to_value", dict(regex=".*MATCH$", target="target_value")),
            ("value_fstring_alias", dict(fstring="prefixed_{value}")),
        ],
    )


@pytest.mark.parametrize(
    "value, candidates, expected",
    [
        ("TARGET_VALUE", ["cand0", "cand1"], [0, 0]),
        ("cand0", ["cand0", "cand1"], [inf, -inf]),
        ("CAND0", ["cand0", "cand1"], [1, 0]),
        ("TARGET_VALUE", ["cand0", "correct_MATCH"], [-inf, inf]),
        ("TARGET_VALUE", ["cand0", "correct_match", "MATCH_but_not_quite_right"], [-inf, inf, -inf]),
        ("VALUE", ["cand0", "prefixed_value", "prefixed", "prefixed_VALUE"], [0, 0.995, 0, 0.995]),
        ("EXACT_MATCH", ["EXACT_MATCH", "correct_match", "correct_MATCH"], [inf, -inf, -inf]),
    ],
)
def test_heuristic_score(value, candidates, expected, heuristic_score):
    actual = list(heuristic_score(value, candidates, None))
    assert actual == expected
