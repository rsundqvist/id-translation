"""Defaults that change in 2.0 warn when omitted, and only then."""

import warnings
from collections.abc import Callable
from typing import Any

import pytest

from id_translation import Translator
from id_translation.fetching import MemoryFetcher, PandasFetcher

CONSTRUCTORS: dict[str, tuple[str, Callable[..., Any]]] = {
    "PandasFetcher": ("return_all", lambda **kw: PandasFetcher(read_path_format="{}.csv", **kw)),
}


@pytest.mark.parametrize("owner", CONSTRUCTORS)
def test_omitted_warns(owner):
    argument, make = CONSTRUCTORS[owner]
    owner = "MagicDict" if argument == "enable_uuid_heuristics" else owner  # Where it applies.
    with pytest.warns(FutureWarning, match=rf"{owner}\({argument}=\.\.\.\) defaults to True"):
        make()


@pytest.mark.parametrize("value", [False, True])
@pytest.mark.parametrize("owner", CONSTRUCTORS)
def test_explicit_is_silent(owner, value):
    argument, make = CONSTRUCTORS[owner]
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        make(**{argument: value})


def test_translator_internals_are_silent():
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        translator: Translator[str, str, int] = Translator({"s": {1: "one"}})
        assert translator.translate(1, "s") == "1:one"
        online: Translator[str, str, int] = Translator(MemoryFetcher({"s": {1: "one"}}, return_all=True))
        assert online.go_offline().translate(1, "s") == "1:one"
