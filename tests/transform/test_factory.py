from pathlib import Path

from id_translation import Translator
from id_translation.transform.types import Transformer


def test_factory():
    translator: Translator[str, str, int] = Translator.from_config(Path(__file__).parent / "config.toml")

    actual = {"guests": [1991, 1999, 2021], "drinking_preferences_bitmask": [2, 3, 0]}
    translator.translate(actual, inplace=True)

    import pandas as pd

    print()
    print(pd.DataFrame(actual))

    assert actual == {
        "guests": ["Oh, it's you again Richard.", "Oh, it's you again Sofia.", "What's up, Morris?"],
        "drinking_preferences_bitmask": ["likes tea", "likes coffee AND likes tea", "just water"],
    }


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
