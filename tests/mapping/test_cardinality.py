import pytest

from id_translation.mapping import Cardinality


def test_count():
    assert len(Cardinality) == 4  # Assumed in the implementation


@pytest.mark.parametrize(
    "arg,expected",
    [
        # Trivial
        (Cardinality.OneToOne, Cardinality.OneToOne),
        (Cardinality.OneToMany, Cardinality.OneToMany),
        (Cardinality.ManyToOne, Cardinality.ManyToOne),
        (Cardinality.ManyToMany, Cardinality.ManyToMany),
        # Correct values
        (Cardinality.OneToOne.value, Cardinality.OneToOne),
        (Cardinality.OneToMany.value, Cardinality.OneToMany),
        (Cardinality.ManyToOne.value, Cardinality.ManyToOne),
        (Cardinality.ManyToMany.value, Cardinality.ManyToMany),
        (Cardinality.OneToOne.name, Cardinality.OneToOne),
        (Cardinality.OneToMany.name, Cardinality.OneToMany),
        (Cardinality.ManyToOne.name, Cardinality.ManyToOne),
        (Cardinality.ManyToMany.name, Cardinality.ManyToMany),
        # Generous
        ("1-1", ValueError),
        ("1:n", ValueError),
        ("n-1", ValueError),
        ("*-*", ValueError),
        # Wrong
        ("1--1", ValueError),
        ("1:many", ValueError),
        ("multiple:single", ValueError),
        ("multiple-multiple", ValueError),
    ],
)
def test_parse(arg, expected):
    if isinstance(expected, Cardinality):
        assert Cardinality.parse(arg, strict=True) == expected
    else:
        with pytest.raises(ValueError):
            Cardinality.parse(arg, strict=True)


@pytest.mark.parametrize(
    "arg,expected",
    [
        ("1-1", Cardinality.OneToOne),
        ("1:n", Cardinality.OneToMany),
        ("n-1", Cardinality.ManyToOne),
        ("*-*", Cardinality.ManyToMany),
    ],
)
def test_generous_parse(arg, expected):
    assert Cardinality.parse(arg, strict=False) == expected


@pytest.mark.parametrize(
    "left_count,right_count,expected",
    [
        # Correct
        (1, 1, Cardinality.OneToOne),
        (1, 2, Cardinality.OneToMany),
        (2, 1, Cardinality.ManyToOne),
        (2, 2, Cardinality.ManyToMany),
        # Extended
        (1, 22, Cardinality.OneToMany),
        (22, 1, Cardinality.ManyToOne),
        (2, 22, Cardinality.ManyToMany),
        # Wrong
        (0, 1, ValueError),
        (1, 0, ValueError),
        (0, 2, ValueError),
        (2, 0, ValueError),
        (-2, 1, ValueError),
        (1, -2, ValueError),
    ],
)
def test_from_counts(left_count, right_count, expected):
    if isinstance(expected, Cardinality):
        assert Cardinality.from_counts(left_count, right_count) == expected
    else:
        with pytest.raises(ValueError):
            assert Cardinality.from_counts(left_count, right_count) == expected


@pytest.mark.parametrize(
    "actual,expected",
    [
        (Cardinality.OneToOne, True),
        (Cardinality.OneToMany, False),
        (Cardinality.ManyToOne, False),
        (Cardinality.ManyToMany, True),
    ],
)
def test_symmetric(actual, expected):
    assert actual.symmetric == expected


@pytest.mark.parametrize(
    "actual,expected",
    [
        (Cardinality.OneToOne, Cardinality.OneToOne),
        (Cardinality.OneToMany, Cardinality.ManyToOne),
        (Cardinality.ManyToOne, Cardinality.OneToMany),
        (Cardinality.ManyToMany, Cardinality.ManyToMany),
    ],
)
def test_inverse(actual, expected):
    assert actual.inverse == expected


def _test_lt_id(t):
    c0, c1, expected = t
    return f"({c0} >= {c1}) is {expected}"


_permutations = [
    # Superset of everything, including self
    (Cardinality.ManyToMany, Cardinality.ManyToMany, True),
    (Cardinality.ManyToMany, Cardinality.ManyToOne, True),
    (Cardinality.ManyToMany, Cardinality.OneToMany, True),
    (Cardinality.ManyToMany, Cardinality.OneToOne, True),
    # Superset of self and 1:1
    (Cardinality.ManyToOne, Cardinality.ManyToMany, False),
    (Cardinality.ManyToOne, Cardinality.ManyToOne, True),
    (Cardinality.ManyToOne, Cardinality.OneToMany, False),
    (Cardinality.ManyToOne, Cardinality.OneToOne, True),
    # Superset of self and 1:1
    (Cardinality.OneToMany, Cardinality.ManyToMany, False),
    (Cardinality.OneToMany, Cardinality.ManyToOne, False),
    (Cardinality.OneToMany, Cardinality.OneToMany, True),
    (Cardinality.OneToMany, Cardinality.OneToOne, True),
    # Superset only of self
    (Cardinality.OneToOne, Cardinality.ManyToMany, False),
    (Cardinality.OneToOne, Cardinality.ManyToOne, False),
    (Cardinality.OneToOne, Cardinality.OneToMany, False),
    (Cardinality.OneToOne, Cardinality.OneToOne, True),
]


@pytest.mark.parametrize("c0, c1, expected", _permutations, ids=map(_test_lt_id, _permutations))
def test_superset(c0, c1, expected):
    """Test whether ``c0`` is a superset of ``c1``."""
    assert (c0 >= c1) is expected
