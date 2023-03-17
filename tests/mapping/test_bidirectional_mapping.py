import itertools

import pytest

from id_translation.mapping import Cardinality, DirectionalMapping
from id_translation.mapping.types import LeftToRight


@pytest.fixture(scope="module")
def mappings_dict() -> LeftToRight[str, str]:
    return {
        "ab": ("AB", "A", "B"),
        "a": ("AB", "A"),
        "b": ("AB", "B"),
    }


@pytest.fixture(scope="module")
def mapping(mappings_dict: LeftToRight[str, str]) -> DirectionalMapping[str, str]:
    return DirectionalMapping(Cardinality.ManyToMany, left_to_right=mappings_dict)


def _sort(a):
    def _sort_tuple(t):
        return tuple(sorted(t))

    return {k: _sort_tuple(v) for k, v in a.items()} if isinstance(a, dict) else _sort_tuple(a)


def test_properties(mapping, mappings_dict):
    assert _sort(mapping.left) == ("a", "ab", "b")
    assert _sort(mapping.left_to_right) == _sort(mappings_dict)

    assert _sort(mapping.right) == ("A", "AB", "B")
    assert _sort(mapping.right_to_left) == _sort(
        {
            "AB": ("ab", "a", "b"),
            "A": ("ab", "a"),
            "B": ("ab", "b"),
        }
    )


@pytest.mark.parametrize(
    "exclude, expected_left, expected_right",
    [
        (True, ("ab",), ("A", "AB", "B")),
        (False, ("a", "b"), ("A", "AB", "B")),
    ],
)
def test_selection(mapping, exclude, expected_left, expected_right):
    mapping = mapping.select_left(["a", "b"], exclude=exclude)
    assert _sort(mapping.left) == expected_left
    assert _sort(mapping.right) == expected_right


@pytest.mark.parametrize("exclude", [True, False])
def test_nonexistent(mapping, mappings_dict, exclude):
    if exclude:
        test_properties(mapping.select_left(["c"], exclude=exclude), mappings_dict)
    else:
        with pytest.raises(KeyError):
            mapping.select_left("c", exclude=exclude)


@pytest.mark.parametrize(
    "test_data, direction",
    tuple(
        itertools.product(
            [
                ({"a": ("a",), "b": ("b",)}, Cardinality.OneToOne),
                ({"a": ("a", "c"), "b": ("b",)}, Cardinality.OneToMany),
                ({"a": ("a",), "b": ("a",)}, Cardinality.ManyToOne),
                ({"ab": ("AB", "A", "B"), "a": ("AB", "A"), "b": ("AB", "B")}, Cardinality.ManyToMany),
            ],
            ("left_to_right", "right_to_left"),
        )
    ),
)
def test_cardinality(test_data, direction):
    data, expected = test_data
    if direction == "right_to_left" and not expected.symmetric:
        expected = expected.inverse
    assert DirectionalMapping(None, **{direction: data}).cardinality == expected


def test_reverse(mapping):
    reverse = mapping.reverse
    assert _sort(reverse.left) == _sort(mapping.right)
    assert _sort(reverse.right) == _sort(mapping.left)

    assert _sort(reverse.left_to_right) == _sort(mapping.right_to_left)
    assert _sort(reverse.right_to_left) == _sort(mapping.left_to_right)


@pytest.mark.parametrize(
    "cardinality, left_to_right, right_to_left, expected_error, expected_message",
    [
        (None, None, None, ValueError, "at least one"),
        (Cardinality.OneToOne, {"ab": ("AB", "A", "B")}, None, ValueError, "cannot cast explicit given "),
        (None, {"ab": ("AB", "A", "B")}, {"ab": ("AB", "A", "B")}, ValueError, "side mismatch"),
    ],
    ids=["No input", "Incorrect cardinality", "Incorrect bidirectional input"],
)
def test_invalid_inputs(cardinality, left_to_right, right_to_left, expected_error, expected_message):
    with pytest.raises(expected_error) as e:
        DirectionalMapping(cardinality, left_to_right=left_to_right, right_to_left=right_to_left, _verify=True)
    assert expected_message in str(e.value).lower()


def test_equal():
    assert DirectionalMapping(left_to_right={"a": ("b", "c"), "b": "d"}) == DirectionalMapping(
        left_to_right={"a": ("b", "c"), "b": "d"}
    )


def test_exclude():
    ans = DirectionalMapping(left_to_right={"a": ("b", "c"), "b": "d"}).select_right("dc", exclude=True)
    assert ans.left_to_right == {"a": ("b",)}
