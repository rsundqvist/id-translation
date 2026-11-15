"""Using the registry while it loads entrypoint integrations raises instead of deadlocking.

An entrypoint module that calls ``MyIO.register()`` at import runs while the registry is being constructed, on the same
thread and under the same lock. With a plain ``Lock`` that hung the process.
"""

import threading
from collections.abc import Callable
from typing import Any

import pytest

from id_translation.dio import _repository, _resolve, get_resolution_order, register_io, reload_integrations, resolve_io
from id_translation.dio.default import ScalarIO
from id_translation.dio.exceptions import DataStructureIOError, RegistryReentryError


class PluginIO(ScalarIO):  # type: ignore[type-arg]
    priority = 42

    @classmethod
    def handles_type(cls, arg: Any) -> bool:  # noqa: ARG003
        return False


REENTRY: dict[str, Callable[[], object]] = {
    "register": lambda: register_io(PluginIO),
    "resolve_io": lambda: resolve_io(1),
    "reload_integrations": reload_integrations,
}


def _call_with_timeout(func: Callable[[], object]) -> BaseException | None:
    """Call `func` in a daemon thread, so that a regression fails the test instead of hanging the suite."""
    result: list[BaseException | None] = []

    def run() -> None:
        try:
            func()
            result.append(None)
        except BaseException as e:
            result.append(e)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=10)
    if thread.is_alive():
        pytest.fail("Deadlock: the registry did not return within 10 seconds.")
    return result[0]


@pytest.fixture
def fresh_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the next registry access to construct, and restore the original registry afterwards.

    The lock is replaced too: if a regression deadlocks, the stuck thread holds this lock forever, not the real one, so
    the rest of the suite still runs.
    """
    monkeypatch.setattr(_resolve, "_INSTANCE", None)
    monkeypatch.setattr(_resolve, "_LOADING", False)  # A deadlocked thread leaves it set.
    monkeypatch.setattr(_resolve, "_INSTANCE_LOCK", type(_resolve._INSTANCE_LOCK)())


@pytest.mark.usefixtures("fresh_registry")
@pytest.mark.parametrize("reentry", REENTRY.values(), ids=REENTRY.keys())
def test_reentry_raises(monkeypatch: pytest.MonkeyPatch, reentry: Callable[[], object]) -> None:
    original = _repository.Repository._load_integrations.__func__  # type: ignore[attr-defined]

    def load_integrations(cls: type[_repository.Repository]) -> Any:
        reentry()  # What an entrypoint module does when it uses the registry at import.
        return original(cls)

    monkeypatch.setattr(_repository.Repository, "_load_integrations", classmethod(load_integrations))

    for _ in range(2):  # A failed load leaves nothing behind; the next access tries again, and fails the same way.
        exc = _call_with_timeout(get_resolution_order)

        assert isinstance(exc, RegistryReentryError)
        assert isinstance(exc, DataStructureIOError)
        assert not isinstance(exc, ImportError), "optional-import guards would swallow it"
        assert any("Do not call register()" in note for note in exc.__notes__)
        assert _resolve._INSTANCE is None
        assert _resolve._LOADING is False

    monkeypatch.undo()  # Restores the original registry too, so force a rebuild.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(_resolve, "_INSTANCE", None)
        mp.setattr(_resolve, "_INSTANCE_LOCK", type(_resolve._INSTANCE_LOCK)())
        assert _call_with_timeout(get_resolution_order) is None
