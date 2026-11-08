import threading
import time
from typing import Any

import pytest

from id_translation import Translator, _transformer_registry, _translator
from id_translation.fetching import MemoryFetcher
from id_translation.transform.types import Transformer


class Tag(Transformer[int]):
    def update_ids(self, _: Any, /) -> None:
        pass

    def update_translations(self, translations: Any, /) -> None:
        for idx in translations:
            translations[idx] += "<tag>"

    def try_add_missing_key(self, key: Any, /, *, translations: Any) -> None:
        pass


class SlowProvider(MemoryFetcher[str, int]):
    """Widens both windows of the first call: source discovery and the get_transformer() pass."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.discoveries = 0

    def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:
        self.discoveries += 1
        time.sleep(0.02)
        return super()._initialize_sources(task_id)

    def get_transformer(self, source: str) -> Tag:  # noqa: ARG002
        time.sleep(0.02)
        return Tag()


@pytest.mark.parametrize("method", ["translate", "map", "initialize_sources", "sources", "sources+translate"])
def test_concurrent_first_use(method):
    translator: Translator[str, str, int] = Translator(SlowProvider({"s": {"id": [1], "name": ["a"]}}))
    barrier = threading.Barrier(16)
    errors: list[BaseException] = []

    def first_use(i: int) -> None:
        # Mixed: discovery through `sources` must take the same lock as a first translation.
        m = method if method != "sources+translate" else ("sources", "translate")[i % 2]
        barrier.wait()
        try:
            if m == "translate":
                translator.translate(1, names="s")
            elif m == "map":
                translator.map({"s": [1]})
            elif m == "sources":
                assert translator.sources == ["s"]
            else:
                translator.initialize_sources()
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=first_use, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert translator.fetcher.discoveries == 1  # type: ignore[attr-defined]
    assert translator.translate(1, names="s") == "1:a<tag>", "the provided transformer must be chained exactly once"

    copy = translator.copy(fetcher="keep")
    copy._tx.lock = None  # type: ignore[assignment]
    copy.initialize_sources()  # A copy of a settled Translator is settled too, so it must never take the lock.


@pytest.mark.parametrize(
    ("module", "after", "kwargs"),
    [
        (_transformer_registry, False, {"fetcher": "keep"}),  # Registry flags read before its transformers are copied.
        (_translator, True, {"fetcher": "copy"}),  # Fetcher cloned before the registry is copied.
        (_translator, True, {"fetcher": "copy", "transformers": {}}),  # Fetcher cloned before discovery is inherited.
    ],
)
def test_copy_during_first_use(monkeypatch, module, after, kwargs):
    translator: Translator[str, str, int] = Translator(SlowProvider({"s": {"id": [1], "name": ["a"]}}))
    errors: list[BaseException] = []

    def initialize() -> None:
        try:
            translator.initialize_sources()
        except BaseException as e:
            errors.append(e)

    first_use = threading.Thread(target=initialize)
    real = module.deepcopy

    def deepcopy(x: Any, memo: Any = None) -> Any:
        if x is not translator._tx._transformers and x is not translator._fetcher:
            return real(x, memo)
        result = real(x, memo) if after else None
        first_use.start()
        first_use.join(timeout=0.5)  # Finishes here unless copy() holds the lock.
        return result if after else real(x, memo)

    monkeypatch.setattr(module, "deepcopy", deepcopy)
    copy = translator.copy(**kwargs)
    monkeypatch.undo()
    first_use.join()

    assert not errors, errors
    fetcher: Any = copy.fetcher
    assert not copy._tx.discovered or fetcher._placeholders is not None, "marked discovered, but the fetcher is not"
    expected = "1:a" if kwargs.get("transformers") == {} else "1:a<tag>"
    assert copy.translate(1, names="s") == expected, "the provided transformer must be chained exactly once"
