"""Each fetcher labels its own log records; nothing accumulates on the shared loggers."""

import logging

import pytest

from id_translation.fetching import MemoryFetcher
from id_translation.fetching.types import IdsToFetch
from id_translation.logging import enable_verbose_debug_messages

SHARED = ("id_translation.fetching", "id_translation.fetching.map")


def make(config_file: str) -> MemoryFetcher[str, int]:
    return MemoryFetcher({"s": {"id": [1], "name": ["one"]}}, identifiers=[config_file])


def test_one_logger_per_class() -> None:
    a, b = make("a.toml"), make("b.toml")

    assert a.logger.logger is b.logger.logger
    assert a.logger.name == "id_translation.fetching.MemoryFetcher"
    assert a.mapper.logger.name == "id_translation.fetching.MemoryFetcher.map"


def test_labels_stick_to_the_public_logger(caplog: pytest.LogCaptureFixture) -> None:
    # What a third-party fetcher does with self.logger.
    a, b = make("a.toml"), make("b.toml")

    with caplog.at_level(logging.WARNING, logger="id_translation"):
        a.logger.warning("from a")
        b.logger.warning("from b")

    labels = {r.getMessage(): r.fetcher_config_file for r in caplog.records}  # type: ignore[attr-defined]
    assert labels == {"from a": "a.toml", "from b": "b.toml"}


def test_assigned_logger(caplog: pytest.LogCaptureFixture) -> None:
    fetcher = make("a.toml")
    fetcher.logger = logging.getLogger("my.logger")  # A plain Logger is wrapped, so the labels stay.

    with caplog.at_level(logging.WARNING, logger="my.logger"):
        fetcher.logger.warning("wrapped")
    assert [r.fetcher_config_file for r in caplog.records] == ["a.toml"]  # type: ignore[attr-defined]

    mine = logging.LoggerAdapter(logging.getLogger("my.logger"), {"mine": True})
    fetcher.logger = mine  # An adapter is the caller's choice and is used as-is.
    assert fetcher.logger is mine


def test_no_filters_accumulate() -> None:
    before = {name: len(logging.getLogger(name).filters) for name in SHARED}
    for i in range(5):
        make(f"{i}.toml")

    assert {name: len(logging.getLogger(name).filters) for name in SHARED} == before


def test_records_are_labelled_by_their_own_fetcher(caplog: pytest.LogCaptureFixture) -> None:
    a, b = make("a.toml"), make("b.toml")  # b is constructed last; it used to label a's records too.

    with enable_verbose_debug_messages(), caplog.at_level(logging.DEBUG, logger="id_translation"):
        a.fetch([IdsToFetch("s", {1})])
        a_records = [r for r in caplog.records if r.name.startswith("id_translation.fetching.MemoryFetcher")]
        caplog.clear()
        b.fetch([IdsToFetch("s", {1})])
        b_records = [r for r in caplog.records if r.name.startswith("id_translation.fetching.MemoryFetcher")]

    assert a_records, "fetcher a logged nothing"
    assert b_records, "fetcher b logged nothing"
    assert {r.name for r in a_records} >= {"id_translation.fetching.MemoryFetcher.map"}, "mapper records missing"
    assert {r.fetcher_config_file for r in a_records} == {"a.toml"}  # type: ignore[attr-defined]
    assert {r.fetcher_config_file for r in b_records} == {"b.toml"}  # type: ignore[attr-defined]
    assert {r.fetcher_class for r in a_records} == {"MemoryFetcher"}  # type: ignore[attr-defined]


def test_caller_extra_is_kept(caplog: pytest.LogCaptureFixture) -> None:
    fetcher = make("a.toml")

    with enable_verbose_debug_messages(), caplog.at_level(logging.DEBUG, logger="id_translation"):
        fetcher.fetch([IdsToFetch("s", {1})])

    records = [r for r in caplog.records if r.name == "id_translation.fetching.MemoryFetcher"]
    assert records
    assert all(hasattr(r, "task_id") for r in records), "the adapter dropped the caller's own extra="
