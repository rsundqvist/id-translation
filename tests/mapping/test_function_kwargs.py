"""A typo in a mapping function's keyword arguments raises when the mapper is built, not at the first call."""

from typing import Any

import pytest

from id_translation.mapping import HeuristicScore, Mapper


def test_score_function_kwargs():
    with pytest.raises(TypeError, match=r"Bad score function arguments \{'add_length_ratio_termm': 1\}"):
        Mapper("modified_hamming", score_function_kwargs={"add_length_ratio_termm": 1})


def test_score_function_kwargs_through_heuristic_score():
    with pytest.raises(TypeError, match="Bad score function arguments"):
        Mapper(HeuristicScore("modified_hamming", []), score_function_kwargs={"bogus": 1})


def test_filter_function_kwargs():
    with pytest.raises(TypeError, match=r"Bad filter function arguments \{'regexx': '.\*'\}"):
        Mapper(filter_functions=[("filter_names", {"regexx": ".*"})])


def test_heuristic_function_kwargs():
    with pytest.raises(TypeError, match="Bad heuristic function arguments"):
        HeuristicScore("equality", [("force_lower_case", {"bogus": 1})])


def test_valid_kwargs_are_accepted():
    Mapper(filter_functions=[("filter_names", {"regex": ".*"})])
    HeuristicScore("equality", [("force_lower_case", {"mutate": True})])  # Consumed by HeuristicScore itself.

    def takes_anything(value: Any, candidates: Any, context: Any, **kwargs: Any) -> set[Any]:  # noqa: ARG001
        return set(candidates)

    Mapper(filter_functions=[(takes_anything, {"whatever": 1})])
