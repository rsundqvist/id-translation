import pickle
import threading
from copy import deepcopy

import pytest

from id_translation._utils import locks
from id_translation._utils.locks import CloneSafeLock, new_lock
from id_translation.fetching import MemoryFetcher


@pytest.mark.parametrize("clone", [deepcopy, lambda lock: pickle.loads(pickle.dumps(lock))])  # noqa: S301
def test_clone_is_new_and_released(clone):
    lock = CloneSafeLock()
    acquired: list[bool] = []
    with lock:
        copied = clone(lock)
        assert type(copied) is CloneSafeLock
        # Another thread can take the clone while the original is held.
        t = threading.Thread(target=lambda: acquired.append(copied.acquire(blocking=False)))
        t.start()
        t.join()
    assert acquired == [True]


def test_disabled_lock_excludes_nothing(monkeypatch):
    monkeypatch.setenv(locks.DISABLE_LOCKS, "true")
    lock = new_lock()
    entered: list[bool] = []

    def enter() -> None:
        lock.__enter__()
        entered.append(True)

    with lock:
        t = threading.Thread(target=enter, daemon=True)
        t.start()
        t.join(timeout=5)  # Would block if the lock excluded anything.
    assert entered == [True]

    fetcher: MemoryFetcher[str, int] = MemoryFetcher({"s": {"id": [1]}})
    assert fetcher.sources == ["s"]  # Discovery still runs, re-entry detection included.


def test_malformed_escape_hatch_raises(monkeypatch):
    monkeypatch.setenv(locks.DISABLE_LOCKS, "maybe")
    with pytest.raises(ValueError, match=locks.DISABLE_LOCKS):
        new_lock()
