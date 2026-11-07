"""Defaults that change in 2.0 warn when omitted, and only then."""

import warnings
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest

from id_translation import Translator
from id_translation.fetching import MemoryFetcher, PandasFetcher
from id_translation.offline import Format, FormatApplier, MagicDict, TranslationMap
from id_translation.offline.types import PlaceholderTranslations

UUID_KEY = str(UUID(int=1))
PHT = PlaceholderTranslations.make("s", {UUID_KEY: "one"})  # UUID-like: where the 2.0 default makes a difference.

CONSTRUCTORS: dict[str, tuple[str, Callable[..., Any]]] = {
    "MemoryFetcher": ("return_all", lambda **kw: MemoryFetcher({"s": {1: "one"}}, **kw)),
    "PandasFetcher": ("return_all", lambda **kw: PandasFetcher(read_path_format="{}.csv", **kw)),
    "TranslationMap": ("enable_uuid_heuristics", lambda **kw: TranslationMap({"s": PHT}, **kw)["s"]),
    "MagicDict": ("enable_uuid_heuristics", lambda **kw: MagicDict({UUID_KEY: "one"}, **kw)),
    "FormatApplier.apply": (
        "enable_uuid_heuristics",
        lambda **kw: FormatApplier(PHT).apply(Format("{id}"), default_fmt=Format("{id}"), **kw),
    ),
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


def test_uuid_default_is_silent_for_keys_that_are_not_uuid_like():
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        assert MagicDict({1: "one"})[1] == "one"
        tmap: TranslationMap[str, str, int] = TranslationMap({"s": PlaceholderTranslations.make("s", {1: "one"})})
        assert tmap["s"][1] == "1:one"
