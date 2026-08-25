"""Enter/exit key events on the go_offline() path.

Complements tests/dvdrental/test_key_events.py, which covers translate() but needs a running database.
"""

import logging

import pytest

from id_translation import Translator
from id_translation.fetching import MemoryFetcher
from id_translation.logging import enable_verbose_debug_messages

DATA = {
    "animals": {"id": [0, 1], "name": ["Tarzan", "Morris"]},
    "people": {"id": [1999, 1991], "name": ["Sofia", "Richard"]},
}


@pytest.fixture
def stages(caplog: pytest.LogCaptureFixture) -> dict[str, list[str]]:
    """Stages in emission order, per `Class.method` key."""
    with enable_verbose_debug_messages(), caplog.at_level(logging.DEBUG, logger="id_translation"):
        Translator[str, str, int](MemoryFetcher(DATA)).go_offline()

    retval: dict[str, list[str]] = {}
    for record in caplog.records:
        if hasattr(record, "event_key"):
            key, _, stage = record.event_key.partition(":")
            retval.setdefault(key, []).append(stage)
    return retval


@pytest.mark.parametrize(
    "key", ["Translator.go_offline", "MemoryFetcher.fetch_all", "MemoryFetcher.initialize_sources"]
)
def test_enter_then_exit(stages, key):
    """Both exit keys were once copy-paste bugs: go_offline emitted 'enter' twice, fetch_all exited as fetch."""
    assert stages[key] == ["enter", "exit"]


def test_no_stray_keys(stages):
    """Every enter is followed by its exit; per-source keys simply repeat the pair."""
    for key, seen in stages.items():
        assert seen == ["enter", "exit"] * (len(seen) // 2), key
