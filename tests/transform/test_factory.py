from pathlib import Path

import pytest
from id_translation import Translator
from id_translation.exceptions import ConfigurationError
from id_translation.transform.types import Transformer

ROOT = Path(__file__).parent


def test_factory():
    translator = Translator[str, str, int].from_config(ROOT / "main.toml", extra_fetchers=[ROOT / "fetcher-only.toml"])

    actual = {"guests": [1991, 1999, 2021], "drinking_preferences_bitmask": [2, 3, 0]}
    translator.translate(actual, copy=False)

    assert actual == {
        "guests": ["Oh, it's you again Richard.", "Oh, it's you again Sofia.", "What's up, Morris?"],
        "drinking_preferences_bitmask": ["likes tea", "likes coffee AND likes tea", "just water"],
    }


def test_overlap_in_main():
    with pytest.raises(ConfigurationError, match="fetcher level"):
        Translator[str, str, int].from_config(
            ROOT / "main.toml", extra_fetchers=[ROOT / "fetcher-and-transformer.toml"]
        )


def test_overlap_in_fetchers():
    with pytest.raises(ConfigurationError, match="another fetcher file"):
        Translator[str, str, int].from_config(
            ROOT / "main.toml",
            extra_fetchers=[ROOT / "fetcher-and-transformer.toml", ROOT / "fetcher-and-transformer.toml"],
        )


class SayHi(Transformer[int]):
    def __init__(self, random_seed):
        from random import Random

        self.random = Random(random_seed)

    def update_ids(self, ids):
        pass

    def update_translations(self, translations):
        greetings = ["Oh, it's you again {}.", "Hello {}!", "What's up, {}?"]

        for idx, name in translations.items():
            phrase = self.random.choice(greetings)
            translations[idx] = phrase.format(name)
