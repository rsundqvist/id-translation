"""An entrypoint module that calls ``MyIO.register()`` at import raises instead of deadlocking the registry.

The module runs while the registry is being constructed, on the same thread and under the same lock.
"""

import threading
from collections.abc import Callable
from typing import Any

import pytest

from id_translation.dio import _repository, _resolve, get_resolution_order, register_io
from id_translation.dio.default import SingleValueIO
from id_translation.dio.exceptions import RegistryReentryError


class PluginIO(SingleValueIO):  # type: ignore[type-arg]
    priority = 42

    @classmethod
    def handles_type(cls, arg: Any) -> bool:  # noqa: ARG003
        return False


def _call_with_timeout(func: Callable[[], object]) -> object:
    """Call `func` in a daemon thread, so that a regression fails the test instead of hanging the suite."""
    result: list[object] = []

    def target() -> None:
        try:
            result.append(func())
        except Exception as e:  # Raised in the calling thread below.
            result.append(e)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout=10)
    if thread.is_alive():
        pytest.fail("Deadlock: the registry did not return within 10 seconds.")
    if isinstance(result[0], Exception):
        raise result[0]
    return result[0]


@pytest.fixture
def fresh_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the next registry access to construct, and restore the original registry afterwards.

    The lock is replaced too: if a regression deadlocks, the stuck thread holds this lock forever, not the real one, so
    the rest of the suite still runs.
    """
    monkeypatch.setattr(_resolve, "_INSTANCE", None)
    # The production lock type: a plain Lock deadlocks here, which the timeout reports.
    monkeypatch.setattr(_resolve, "_INSTANCE_LOCK", type(_resolve._INSTANCE_LOCK)())


@pytest.mark.usefixtures("fresh_registry")
def test_register_while_loading_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    original = _repository.Repository._load_integrations.__func__  # type: ignore[attr-defined]

    def load_integrations(cls: type[_repository.Repository]) -> Any:
        register_io(PluginIO)  # What an entrypoint module does at import.
        return original(cls)

    monkeypatch.setattr(_repository.Repository, "_load_integrations", classmethod(load_integrations))

    with pytest.raises(RegistryReentryError, match="while loading"):
        _call_with_timeout(get_resolution_order)
    assert _resolve._LOADING is False
    assert _resolve._INSTANCE is None, "the failed load must not be kept"
