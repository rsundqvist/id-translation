from pathlib import Path

import pytest
from numpy.random import default_rng

from id_translation.mapping import score_functions as sf

WORDS = Path(__file__).parent.joinpath("words.txt").read_text().splitlines()


@pytest.mark.parametrize(
    "func, dtype",
    [
        (sf.equality, str),
        (sf.equality, int),
        (sf.modified_hamming, str),
    ],
)
def test_stable(func, dtype):
    """Score function should respect input order."""
    candidates = make(12, dtype)
    values = make(6, dtype)

    for v in values:
        actual_scores = list(func(v, candidates.copy(), None))
        assert all([isinstance(s, float) for s in actual_scores]), "Bad return type"

        for i, c in enumerate(candidates):
            random_candidates = make(12, dtype, seed=i)
            random_candidates[i] = c
            scores = list(func(v, random_candidates, None))
            assert scores[i] == actual_scores[i]


def make(count, dtype, seed=2019_05_11):
    if dtype is int:
        return make_int(count, seed)
    if dtype is str:
        return make_str(count, seed)
    raise AssertionError


def make_str(count, seed):
    ans = []

    rng = default_rng(seed)

    for i in range(count):
        joiner = ["-", "_"][i % 2]
        ans.append(joiner.join(rng.choice(WORDS, rng.integers(1, 4))))

    return ans


def make_int(count, seed):
    rng = default_rng(seed)
    return list(rng.integers(-10, 10, count))


def test_positional_penalty_only_breaks_ties():
    from id_translation.mapping import HeuristicScore, Mapper

    candidates = [f"t{i:03d}" for i in range(149)] + ["animals"]  # A good match, last of many.
    score: HeuristicScore[str, str, None] = HeuristicScore("modified_hamming", ["like_database_table"])
    mapper: Mapper[str, str, None] = Mapper(score, min_score=0.9)
    assert mapper.apply(["animal_id"], candidates).flatten() == {"animal_id": "animals"}
