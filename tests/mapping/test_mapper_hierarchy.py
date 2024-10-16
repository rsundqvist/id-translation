from itertools import product
from typing import Any, ClassVar

import pytest

from id_translation.mapping import Cardinality, HeuristicScore, Mapper
from id_translation.mapping.exceptions import AmbiguousScoreError

POSSIBLE_NUMBER_OF_LEGS = [0, 2, 3, 4]
NUMBER_OF_LEGS = {
    "cat": 4,
    "dog": 4,
    "three-legged cat": 3,
    "human": 2,
    "snake": 0,
}

CASES = list(
    product(
        Cardinality,
        product([False, True], repeat=4),
    )
)


def make_id(case: Any) -> str:
    cardinality, (override_function, static_override, filters, short_circuit) = case

    x: Any = f"{override_function=},{static_override=},{filters=},{short_circuit=}".split(",")
    x = " | ".join([s.split("=")[0] for s in filter(lambda s: s.endswith("True"), x)])
    x = x or "baseline"
    return f"{cardinality.name}: <{x}>"


@pytest.mark.parametrize("cardinality, run_params", CASES, ids=map(make_id, CASES))
def test_hierarchy(cardinality, run_params):
    run(cardinality, *run_params)


def run(
    cardinality,
    use_override_function,
    use_static_override,
    use_filter,
    use_short_circuit,
):
    values = NUMBER_OF_LEGS.copy()
    score = HeuristicScore(
        score_function=lambda v, c, _cxt: [float(c == NUMBER_OF_LEGS[v]) for c in c],
        heuristics=[ShortCircuit.dogs_have_4_legs] if use_short_circuit else (),
    )
    mapper = Mapper(
        score,
        overrides=StaticOverride.nobody_gets_any_legs if use_static_override else None,
        filter_functions=[(FilterFunction.nobody_has_4_legs, {})] if use_filter else (),
        cardinality=cardinality,
    )

    if cardinality.one_left and not any(
        [
            use_override_function,
            use_static_override,
            use_filter,
            use_short_circuit,
        ]
    ):
        with pytest.raises(AmbiguousScoreError, match=f"score=1.*cardinality='{cardinality.name}'"):
            mapper.apply(values, POSSIBLE_NUMBER_OF_LEGS)
        return

    actual = mapper.apply(
        values=values,
        candidates=POSSIBLE_NUMBER_OF_LEGS,
        override_function=OverrideFunction.humans_have_4_legs if use_override_function else None,
    ).left_to_right

    if use_override_function:
        for animal, legs in OverrideFunction.expected(cardinality).items():
            assert actual.pop(animal, legs) == legs, f"OverrideFunction: {animal=}"

    if use_static_override:
        for animal, legs in StaticOverride.expected(cardinality).items():
            assert actual.pop(animal, legs) == legs, f"StaticOverride: {animal=}"

    if use_filter:
        for animal, legs in FilterFunction.expected(cardinality).items():
            assert actual.pop(animal, legs) == legs, f"FilterFunction: {animal=}"

    if use_short_circuit:
        for animal, legs in ShortCircuit.expected(cardinality).items():
            assert actual.pop(animal, legs) == legs, f"ShortCircuit: {animal=}"

    for animal, legs in Baseline.expected(cardinality).items():
        assert actual.pop(animal, legs) == legs, f"Baseline: {animal=}"

    assert not actual, "This isn't supposed to happen!"


class Baseline:
    @classmethod
    def expected(cls, cardinality):
        number_of_legs = NUMBER_OF_LEGS.copy()
        if cardinality.one_left:
            del number_of_legs["dog"]
        return {v: (n,) for v, n in number_of_legs.items()}

    @classmethod
    def error(cls, cardinality):
        return f"{cls.__name__}: {cardinality=}"


class ShortCircuit:
    @staticmethod
    def dogs_have_4_legs(v, c, cxt):
        return {4} if v == "dog" else set()

    @classmethod
    def expected(cls, cardinality):
        # Cat usually has higher prio (first in iteration order), which is the main difference from the baseline.
        return {"dog": (4,)}


class FilterFunction:
    @staticmethod
    def nobody_has_4_legs(v, c, cxt):
        ans = set(c)
        ans.discard(4)
        return ans

    @classmethod
    def expected(cls, cardinality):
        return Baseline.expected(cardinality)


class StaticOverride:
    nobody_gets_any_legs: ClassVar = {animal: 0 for animal in NUMBER_OF_LEGS}

    @classmethod
    def expected(cls, cardinality):
        return {a: (0,) for a in NUMBER_OF_LEGS}


class OverrideFunction:
    @staticmethod
    def humans_have_4_legs(v, c, cxt):
        return 4 if "human" in v else None

    @classmethod
    def expected(cls, cardinality):
        return {"human": (4,)}
