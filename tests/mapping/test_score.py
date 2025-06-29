import warnings

import pytest

from id_translation.mapping import Cardinality, DirectionalMapping

with warnings.catch_warnings():
    warnings.simplefilter("ignore", category=UserWarning)
    from id_translation.mapping.matrix import ScoreHelper, ScoreMatrix


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


def test_axis_assignment_equivalent_to_pandas():
    matrix = make_scores()

    matrix[1, :] = -1
    assert (matrix.to_pandas().loc[1, :] == -1).all(), "row assignment"
    matrix[:, "c2"] = -2
    assert (matrix.to_pandas().loc[:, "c2"] == -2).all(), "column assignment"


def test_missing_index_assignment():
    matrix = make_scores()

    matrix[1000, :] = -1
    assert (matrix.to_pandas().loc[1000, :] == -1).all(), "row assignment"
    matrix[:, "c2000"] = -2
    assert (matrix.to_pandas().loc[:, "c2000"] == -2).all(), "column assignment"


def test_native_string():
    actual = make_scores().to_native_string()
    assert actual in EXPECTED_NATIVE_STRING


EXPECTED_NATIVE_STRING = """
v/c   ┃ c0    ┃ c1    ┃ c2    ┃ c3    ┃ c4   
━━━━━━╋━━━━━━━╋━━━━━━━╋━━━━━━━╋━━━━━━━╋━━━━━━
0     ┃  0.00 ┃  1.00 ┃  2.00 ┃  3.00 ┃  4.00
1     ┃  5.00 ┃  6.00 ┃  7.00 ┃  8.00 ┃  9.00
2     ┃ 10.00 ┃ 11.00 ┃ 12.00 ┃ 13.00 ┃ 14.00
3     ┃ 15.00 ┃ 16.00 ┃ 17.00 ┃ 18.00 ┃ 19.00
"""  # noqa: W291


def make_scores() -> ScoreMatrix[int, str]:
    grid = [
        [0.0, 1.0, 2.0, 3.0, 4.0],
        [5.0, 6.0, 7.0, 8.0, 9.0],
        [10.0, 11.0, 12.0, 13.0, 14.0],
        [15.0, 16.0, 17.0, 18.0, 19.0],
    ]
    return ScoreMatrix(values=[0, 1, 2, 3], candidates=["c0", "c1", "c2", "c3", "c4"], grid=grid)
