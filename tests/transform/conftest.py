"""Shared helpers for transformer tests."""

from collections.abc import Mapping, MutableMapping, Sequence

from id_translation import Translator
from id_translation.fetching import MemoryFetcher
from id_translation.transform.types import Transformer

DATA = {"bitmasks": {"id": [1, 2], "name": ["one", "two"]}}


class Marker(Transformer[int]):
    """Appends ``|<tag>`` to all translations, making a doubled application visible."""

    def __init__(self, tag: str) -> None:
        self.tag = tag

    def update_ids(self, ids: set[int], /) -> None: ...

    def update_translations(self, translations: dict[int, str], /) -> None:
        for key in translations:
            translations[key] += f"|{self.tag}"

    def try_add_missing_key(self, key: int, /, *, translations: MutableMapping[int, str]) -> None: ...

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.tag!r})"


def make_translator(
    how: str,
    transformers: Mapping[str, Transformer[int] | Sequence[Transformer[int]]],
    *,
    return_all: bool = True,
) -> Translator[str, str, int]:
    """Register `transformers` through the constructor or the method, depending on `how`."""
    fetcher = MemoryFetcher[str, int](DATA, return_all=return_all)

    if how == "init":
        return Translator[str, str, int](fetcher, transformers=transformers)

    translator = Translator[str, str, int](fetcher)
    for source, transformer in transformers.items():
        translator.register_transformer(source, transformer)
    return translator


def translate(translator: Translator[str, str, int], idx: int = 1) -> str:
    return translator.translate((idx,), names="bitmasks")[0]
