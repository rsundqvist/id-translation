from math import inf

import pytest

from id_translation.mapping import Cardinality, DirectionalMapping, ScoreMatrix
from id_translation.mapping._score_helper import Record, Reject, ScoreHelper


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
    score = make_scores()
    dm: DirectionalMapping[int, str] = ScoreHelper(score, min_score).to_directional_mapping(cardinality)
    actual = dm.left_to_right
    assert actual == expected


def test_row_assignment_equivalent_to_pandas():
    matrix = make_scores()

    matrix._set_row(1, -1)
    assert (matrix.to_pandas().loc[1, :] == -1).all(), "row assignment"


def test_missing_index_assignment():
    matrix = make_scores()

    matrix._set_row(1000, -1)
    assert (matrix.to_pandas().loc[1000, :] == -1).all(), "row assignment"
    matrix._set(0, "c2000", -2)
    assert matrix.to_dict()[(0, "c2000")] == -2
    assert (matrix.to_pandas().loc[1000, "c2000"]) == -inf


def test_grid_is_copied():
    row = [0.0]
    grid = [row, row]
    matrix = ScoreMatrix(values=["a", "b"], candidates=["c"], grid=grid)
    matrix._set("a", "c", 1.0)
    matrix._set("a", "d", 2.0)
    assert grid == [[0.0], [0.0]]
    assert matrix.to_dict() == {("a", "c"): 1.0, ("a", "d"): 2.0, ("b", "c"): 0.0, ("b", "d"): -inf}


def test_native_string():
    actual = make_scores()._to_native_string()
    assert actual in EXPECTED_NATIVE_STRING


@pytest.mark.parametrize("score, expected", [(-inf, "-inf"), (100.0, "100.00")])
def test_native_string_fits_wide_scores(score, expected):
    lines = ScoreMatrix(values=["a"], candidates=["b"], grid=[[score]])._to_native_string().splitlines()
    assert lines[2].endswith(f" {expected}")
    assert len({len(line) for line in lines}) == 1


def test_native_string_of_an_empty_matrix():
    assert ScoreMatrix(values=[], candidates=[], grid=[])._to_native_string(lines=False) == "v/c"


@pytest.mark.parametrize("value", [("input", "0"), None])
def test_native_string_with_labels_that_take_no_format_spec(value):
    """The pandas-free table used by DEBUG logging; tuple names are common, and None takes no format spec either."""
    actual = ScoreMatrix(values=[value], candidates=[("db", "0")], grid=[[1.0]])._to_native_string(lines=False)
    assert actual.splitlines()[1].startswith(str(value))


EXPECTED_NATIVE_STRING = """
v/c   ┃ c0    ┃ c1    ┃ c2    ┃ c3    ┃ c4   
━━━━━━╋━━━━━━━╋━━━━━━━╋━━━━━━━╋━━━━━━━╋━━━━━━
0     ┃  0.00 ┃  1.00 ┃  2.00 ┃  3.00 ┃  4.00
1     ┃  5.00 ┃  6.00 ┃  7.00 ┃  8.00 ┃  9.00
2     ┃ 10.00 ┃ 11.00 ┃ 12.00 ┃ 13.00 ┃ 14.00
3     ┃ 15.00 ┃ 16.00 ┃ 17.00 ┃ 18.00 ┃ 19.00
"""  # noqa: W291


def test_bad_grid_row_count():
    with pytest.raises(ValueError, match=r"Bad grid: Number of rows 3 must match the number of values=4\."):
        ScoreMatrix(values=[0, 1, 2, 3], candidates=["c0", "c1"], grid=[[0.0, 1.0], [2.0, 3.0], [4.0, 5.0]])


def test_bad_grid_column_count():
    with pytest.raises(
        ValueError,
        match=r"Bad grid\[1\] row \(value=1\): Number of columns 1 must match the number of candidates=2\.",
    ):
        ScoreMatrix(values=[0, 1], candidates=["c0", "c1"], grid=[[0.0, 1.0], [2.0]])


def make_scores() -> ScoreMatrix[int, str]:
    grid = [
        [0.0, 1.0, 2.0, 3.0, 4.0],
        [5.0, 6.0, 7.0, 8.0, 9.0],
        [10.0, 11.0, 12.0, 13.0, 14.0],
        [15.0, 16.0, 17.0, 18.0, 19.0],
    ]
    return ScoreMatrix(values=[0, 1, 2, 3], candidates=["c0", "c1", "c2", "c3", "c4"], grid=grid)


@pytest.mark.parametrize("full", [False, True])
def test_explain_superseded_is_balanced(full):
    record = Record("horse", "4", -inf)
    for reject in (
        Reject(record, superseding_value=Record("horse", "5", inf)),
        Reject(record, superseding_candidate=Record("dog", "4", inf)),
    ):
        explanation = reject.explain(0.9, full=full)
        assert explanation.count("(") == explanation.count(")") == 1, explanation
