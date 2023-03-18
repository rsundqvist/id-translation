from pathlib import Path

import pytest
from numpy.random import choice, randint

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
            random_candidates = make(12, dtype)
            random_candidates[i] = c
            scores = list(func(v, random_candidates, None))
            assert scores[i] == actual_scores[i]


def make(count, dtype):
    if dtype == int:
        return make_int(count)
    if dtype == str:
        return make_str(count)
    raise AssertionError


def make_str(count):
    ans = []

    for i in range(count):
        joiner = ["-", "_"][i % 2]
        ans.append(joiner.join(choice(WORDS, randint(1, 4))))

    return ans


def make_int(count):
    return list(randint(-10, 10, count))
