import warnings

import numpy as np
import pandas as pd
import pytest

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=UserWarning)
    from id_translation.mapping import Cardinality, DirectionalMapping, support


def test_enable_verbose_debug_messages():
    from id_translation.mapping import filter_functions, heuristic_functions, score_functions

    before = False, True, False
    filter_functions.VERBOSE, heuristic_functions.VERBOSE, score_functions.VERBOSE = before

    with support.enable_verbose_debug_messages():
        assert all((filter_functions.VERBOSE, heuristic_functions.VERBOSE, score_functions.VERBOSE))

    assert before == (filter_functions.VERBOSE, heuristic_functions.VERBOSE, score_functions.VERBOSE)


@pytest.mark.parametrize(
    "cardinality, min_score, expected",
    [
        (Cardinality.OneToOne, 0, {3: ("c4",), 2: ("c3",), 1: ("c2",), 0: ("c1",)}),
        (Cardinality.OneToOne, 10, {3: ("c4",), 2: ("c3",)}),
        (Cardinality.OneToMany, 0, {3: ("c4", "c3", "c2", "c1", "c0")}),
        (Cardinality.OneToMany, 10, {3: ("c4", "c3", "c2", "c1", "c0")}),
        (Cardinality.ManyToOne, 0, {3: ("c4",), 2: ("c4",), 1: ("c4",), 0: ("c4",)}),
        (Cardinality.ManyToOne, 10, {3: ("c4",), 2: ("c4",)}),
        (
            Cardinality.ManyToMany,
            0,
            {
                3: ("c4", "c3", "c2", "c1", "c0"),
                2: ("c4", "c3", "c2", "c1", "c0"),
                1: ("c4", "c3", "c2", "c1", "c0"),
                0: ("c4", "c3", "c2", "c1", "c0"),
            },
        ),
        (Cardinality.ManyToMany, 10, {3: ("c4", "c3", "c2", "c1", "c0"), 2: ("c4", "c3", "c2", "c1", "c0")}),
    ],
)
def test_natural_number_mapping(cardinality, min_score, expected):
    score = pd.DataFrame(np.arange(0, 20).reshape((4, -1)))
    score.columns = list(map("c{}".format, score))
    score.columns.name = "candidates"  # type: ignore[attr-defined]
    score.index.name = "values"
    dm: DirectionalMapping[int, str] = support.MatchScores(score, min_score).to_directional_mapping(cardinality)
    actual = dm.left_to_right
    assert actual == expected
