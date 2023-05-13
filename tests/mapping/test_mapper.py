import pytest
from rics.collections.dicts import InheritedKeysDict

from id_translation.mapping import Cardinality, Mapper, exceptions
from id_translation.mapping.exceptions import MappingError, ScoringDisabledError, UserMappingError, UserMappingWarning
from id_translation.mapping.types import MatchTuple


def _substring_score(k, c, _):
    for ci in c:
        yield float(k in ci) / len(ci)


@pytest.fixture(scope="module")
def candidates() -> MatchTuple[str]:
    return "a", "ab", "b"


def test_default(candidates):
    mapper: Mapper[str, str, None] = Mapper()
    assert mapper.apply(candidates, ["a"]).left_to_right == {"a": ("a",)}
    assert mapper.apply(candidates, ["b"]).left_to_right == {"b": ("b",)}
    assert mapper.apply(candidates, ["a", "b"]).left_to_right == {"a": ("a",), "b": ("b",)}


def test_with_overrides(candidates):
    mapper: Mapper[str, str, None] = Mapper(overrides={"a": "fixed"})
    assert mapper.apply(["a"], candidates).left_to_right == {"a": ("fixed",)}
    assert mapper.apply(["b"], candidates).left_to_right == {"b": ("b",)}
    assert mapper.apply(["a", "b"], candidates).left_to_right == {"a": ("fixed",), "b": ("b",)}


@pytest.mark.parametrize(
    "user_override, expected",
    [
        ("ab", ("ab",)),
        (None, ("fixed",)),
    ],
)
def test_user_override(candidates, user_override, expected):
    mapper: Mapper[str, str, None] = Mapper(overrides={"a": "fixed"})
    actual = mapper.apply(["a"], candidates, override_function=lambda *args: user_override).left_to_right
    assert actual == {"a": expected}


def test_user_overrides_ignore_unknown(candidates):
    mapper: Mapper[str, str, None] = Mapper(overrides={"a": "fixed"}, unknown_user_override_action="warn")
    with pytest.warns(UserMappingWarning):
        assert mapper.apply(["a"], candidates, override_function=lambda *args: "bad").left_to_right == {"a": ("fixed",)}

    mapper = Mapper(overrides={"a": "fixed"}, unknown_user_override_action="raise")
    with pytest.raises(UserMappingError):
        mapper.apply(["a"], candidates, override_function=lambda *args: "bad")


@pytest.mark.parametrize(
    "values, expected, allow_multiple",
    [
        ("a", {"a": ("a", "ab")}, True),
        ("b", {"b": ("b", "ab")}, True),
        ("ab", {"a": ("a", "ab"), "b": ("b", "ab")}, True),
        ("a", {"a": ("a",)}, False),
        ("b", {"b": ("b",)}, False),
        ("ab", {"a": ("a",), "b": ("b",)}, False),
    ],
)
def test_multiple_matches(values, expected, allow_multiple, candidates):
    mapper: Mapper[str, str, None] = Mapper(
        min_score=0.1,
        score_function=_substring_score,
        cardinality=None if allow_multiple else Cardinality.OneToOne,
    )
    assert mapper.apply(values, candidates).left_to_right == expected


@pytest.mark.parametrize(
    "values, expected, allow_multiple",
    [
        ("a", {"a": ("fixed",)}, True),
        ("b", {"b": ("b", "ab")}, True),
        ("ab", {"a": ("fixed",), "b": ("b", "ab")}, True),
        ("a", {"a": ("fixed",)}, False),
        ("b", {"b": ("b",)}, False),
        ("ab", {"a": ("fixed",), "b": ("b",)}, False),
    ],
)
def test_multiple_matches_with_overrides(values, expected, allow_multiple, candidates):
    mapper: Mapper[str, str, None] = Mapper(
        overrides={"a": "fixed"},
        min_score=0.1,
        score_function=_substring_score,
        cardinality=None if allow_multiple else Cardinality.OneToOne,
    )
    assert mapper.apply(values, candidates).left_to_right == expected


def test_mapping_failure(candidates):
    mapper: Mapper[int, str, None] = Mapper(unmapped_values_action="raise")
    with pytest.raises(exceptions.MappingError):
        mapper.apply((3, 4), candidates)


def test_bad_filter(candidates):
    mapper: Mapper[int, str, None] = Mapper(filter_functions=[(lambda *_: {3, 4}, {})])
    with pytest.raises(exceptions.BadFilterError):
        mapper.apply((3, 4), candidates)


@pytest.mark.parametrize(
    "values, expected",
    [
        ([1] + [2] * 999, {1: 0}),
        ([2] + [1] * 999, {2: 0}),
    ],
)
def test_conflicting_overrides_prioritizes_first(values, expected):
    mapper: Mapper[int, int, None] = Mapper(
        score_function=lambda *_: [1] * len(values), cardinality="1:1", overrides={v: 0 for v in values}
    )
    assert mapper.apply(values, reversed(values)).flatten() == expected


@pytest.mark.parametrize(
    "values, expected",
    [
        ([1] + [2] * 999, {1: 0}),
        ([2] + [1] * 999, {2: 0}),
    ],
)
def test_conflicting_function_overrides_prioritizes_first(values, expected):
    mapper: Mapper[int, int, None] = Mapper(
        score_function=lambda *_: [1] * len(values), unknown_user_override_action="ignore", cardinality="1:1"
    )
    assert mapper.apply(values, reversed(values), override_function=lambda *_: 0).flatten() == expected


def test_context_sensitive_overrides():
    mapper = Mapper(
        overrides=InheritedKeysDict(
            default={"value0": "default0", "value1": "default1"},
            specific={
                0: {"value0": "c0-override-0"},
                1: {"value0": "c1-override-0"},
            },
        )
    )
    values = ["value0", "value1"]
    assert mapper.apply(values, [""], 0).flatten() == {"value0": "c0-override-0", "value1": "default1"}
    assert mapper.apply(values, [""], 1).flatten() == {"value0": "c1-override-0", "value1": "default1"}
    assert mapper.apply(values, [""], 1999).flatten() == {"value0": "default0", "value1": "default1"}

    with pytest.raises(MappingError, match="Must pass a context"):
        mapper.apply(values, [""])


def test_copy():
    assert Mapper() == Mapper()
    assert Mapper() == Mapper().copy()


@pytest.mark.parametrize(
    "values, expected",
    [
        ("a", {"a": ("fixed",)}),
        ("aa", {"a": ("fixed",)}),
        ("ab", None),
        ("b", None),
        ("", {}),
    ],
)
def test_disabled(values, expected, candidates):
    mapper: Mapper[str, str, None] = Mapper(score_function="disabled", overrides={"a": "fixed"})

    if expected is None:
        with pytest.raises(ScoringDisabledError, match="disabled"):
            mapper.apply(values, candidates)
    else:
        assert mapper.apply(values, candidates).left_to_right == expected
