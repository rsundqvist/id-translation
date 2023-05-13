import pytest

from id_translation.mapping import HeuristicScore

CS = float("inf")  # Short-circuited/chosen by override
F = float("-inf")  # Filtered


def _run(value, candidates, expected):
    assert len(candidates) == len(expected)

    heuristic_score: HeuristicScore[str, str, None] = HeuristicScore(
        "equality",
        heuristics=[
            ("force_lower_case", dict(mutate=True)),
            ("short_circuit", dict(value_regex="^re_.*", target_candidate="target")),
            ("value_fstring_alias", dict(fstring="prefixed_{value}")),
        ],
    )
    actual = list(heuristic_score(value, candidates, None))
    assert actual == expected


def test_plain():
    _run("value", candidates=["VALUE", "NOT_VALUE", "value"], expected=[1, 0, 1])


@pytest.mark.parametrize(
    "value, candidates, expected",
    [
        ("re_value", ["candidate0", "candidate1"], [0, 0]),  # Neither condition met
        ("re_value", ["candidate0", "target"], [F, CS]),  # Both met
        ("value", ["candidate0", "target"], [0, 0]),  # Only target condition
        ("re_value", ["candidate0", "candidate1"], [0, 0]),  # Only value condition
    ],
)
def test_short_circuiting(value, candidates, expected):
    _run(value, candidates, expected)


@pytest.mark.parametrize(
    "value, candidates, expected",
    [
        ("VALUE", ["candidate0", "prefixed_value", "prefixed_VALUE", "prefixed"], [0, 0.995, 0.995, 0]),
        ("value", ["candidate0", "prefixed_value", "prefixed", "prefixed_VALUE"], [0, 0.995, 0, 0.995]),
        ("value", ["candidate0", "prefixed_value", "VALUE"], [0, 0.995, 1]),  # VALUE matches after fewer steps
    ],
)
def test_alias(value, candidates, expected):
    _run(value, candidates, expected)
