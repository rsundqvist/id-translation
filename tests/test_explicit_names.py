import pandas as pd
import pytest

from id_translation import Translator
from id_translation.exceptions import MissingNamesError
from id_translation.fetching import MemoryFetcher

DATA = {"people": {"id": [1], "name": ["Ada"]}}


def _translator(online: bool) -> Translator[str, str, int]:
    translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA), fmt="{name}")
    if not online:
        translator.go_offline()
    return translator


@pytest.mark.parametrize("online", [True, False])
@pytest.mark.parametrize(
    "translatable",
    [{"a": 1}, pd.DataFrame({"a": [1]}), pd.MultiIndex.from_arrays([[1]], names=["a"])],
    ids=["dict", "frame", "multiindex"],
)
@pytest.mark.parametrize("names", [["a", "b"], {"a": "people", "b": "people"}], ids=["list", "dict"])
def test_explicit_name_missing_from_the_data(online, translatable, names):
    with pytest.raises(MissingNamesError, match=r"Names \['b'\] are not in the") as exc_info:
        override = None if isinstance(names, dict) else (lambda *_: "people")  # A names dict maps by itself.
        _translator(online).translate(translatable, names=names, override_function=override)
    assert exc_info.value.missing == ("b",)
    assert exc_info.value.__notes__ == ["Hint: Available names: ['a']."]


@pytest.mark.parametrize("translatable", [pd.Series([1], name="s"), [1]], ids=["named series", "list"])
def test_positional_data_takes_any_name(translatable):
    """A Series' own name, or a list's lack of one, is not a key: the given name is simply what it is called."""
    translated = _translator(online=True).translate(translatable, names="people")
    assert list(translated) == ["Ada"]
