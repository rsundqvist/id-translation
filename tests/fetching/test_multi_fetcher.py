import logging
import pickle
import threading
from collections.abc import Collection
from copy import deepcopy
from itertools import combinations
from typing import Any, Never

import pandas as pd
import pytest

from id_translation import Translator
from id_translation.fetching import AbstractFetcher, MemoryFetcher, MultiFetcher, SqlFetcher, exceptions
from id_translation.fetching.exceptions import FetcherWarning
from id_translation.fetching.types import IdsToFetch
from id_translation.mapping.exceptions import AmbiguousScoreError
from id_translation.offline.types import PlaceholderTranslations, SourcePlaceholderTranslations
from id_translation.testing import TestFetcher as _TestFetcher  # Aliased: pytest collects Test* classes
from id_translation.types import IdTypes

from ..conftest import ROOT, NotCloneableFetcher

ALL_SOURCES = ["animals", "big_table", "huge_table", "humans"]


@pytest.fixture
def fetchers(data: dict[str, pd.DataFrame]) -> Collection[AbstractFetcher[str, int]]:
    primary_fetcher: MemoryFetcher[str, int] = MemoryFetcher({"humans": data["humans"], "animals": data["animals"]})
    empty_fetcher: MemoryFetcher[str, int] = MemoryFetcher({}, optional=True)

    data = {k: v for k, v in data.items() if k != "animals"}
    fallback_fetcher: MemoryFetcher[str, int] = MemoryFetcher(data)

    with pytest.warns(FetcherWarning, match="empty"):
        sql_fetcher: SqlFetcher[int] = SqlFetcher("sqlite://", whitelist_tables=())  # No tables allowed!
    return primary_fetcher, empty_fetcher, fallback_fetcher, sql_fetcher


@pytest.fixture
def multi_fetcher(fetchers):
    fetcher = MultiFetcher(*fetchers, on_source_conflict="ignore")
    yield fetcher
    fetcher.close()


@pytest.fixture(scope="module")
def expected(data):
    return MemoryFetcher(data).fetch_all()


def test_sources(multi_fetcher):
    assert sorted(multi_fetcher.sources) == ALL_SOURCES


def test_sources_per_child(multi_fetcher):
    children = multi_fetcher.children
    assert len(children) == 3
    assert children[0].sources == ["humans", "animals"]
    assert sorted(children[1].sources) == ["big_table", "huge_table", "humans"]
    assert sorted(children[2].sources) == []


def test_source_to_child_mapping(multi_fetcher):
    children = multi_fetcher.children
    assert len(children) == 3

    assert multi_fetcher.get_child("humans") == children[0]
    assert multi_fetcher.get_child("animals") == children[0]
    assert children[1].sources == ["humans", "big_table", "huge_table"]
    assert multi_fetcher.get_sources(children[1]) == ["big_table", "huge_table"]


def test_child_accessors_reject_strangers(multi_fetcher):
    stranger = deepcopy(multi_fetcher.children[0])  # A copy, but not a child; neither is a raw id() or rank.

    for bad in [stranger, 0, id(multi_fetcher.children[0])]:
        with pytest.raises(ValueError, match="Not a child of this MultiFetcher"):
            multi_fetcher.get_sources(bad)
        with pytest.raises(ValueError, match="Not a child of this MultiFetcher"):
            multi_fetcher.format_child(bad)

    with pytest.raises(exceptions.UnknownSourceError):
        multi_fetcher.get_child("no-such-source")


def test_placeholders(multi_fetcher):
    assert multi_fetcher.placeholders == {
        "animals": ["id", "name", "is_nice"],
        "humans": ["id", "name", "gender"],
        "big_table": ["id"],
        "huge_table": ["id"],
    }


def test_process_future_keeps_only_the_owners_translations():
    children: list[MemoryFetcher[str, int]] = [MemoryFetcher({f"s{i}": {"id": [1, 2, 3]}}) for i in range(3)]
    fetcher: MultiFetcher[str, int] = MultiFetcher(*children)
    fetcher.initialize_sources()
    ans: SourcePlaceholderTranslations[str] = {}

    def process(source: str, child: MemoryFetcher[str, int]) -> PlaceholderTranslations[str]:
        pht = PlaceholderTranslations.make(source, pd.DataFrame([1], columns=["id"]))
        fetcher._process_future_result({source: pht}, id(child), ans, operation="FETCH", task_id=0)
        return pht

    owned = process("s1", children[1])
    assert ans == {"s1": owned}

    # A higher-ranked child returning another child's source must not win.
    with pytest.warns(exceptions.DuplicateSourceWarning, match=r"returned by the rank-0 .* belongs to the rank-1"):
        process("s1", children[0])
    assert ans == {"s1": owned}

    with pytest.warns(exceptions.FetcherWarning, match="belongs to no fetcher"):
        process("unknown", children[2])
    assert ans == {"s1": owned}


def test_fetch_all(multi_fetcher, expected, caplog):
    actual = multi_fetcher.fetch_all()

    assert actual == expected
    assert not [r for r in caplog.records if r.getMessage().startswith("Dropping")]


def test_fetch_all_skips_lost_sources(data):
    class Fallback(MemoryFetcher[str, int]):
        def fetch_translations(self, instr):
            assert instr.source != "humans", "lost to the primary fetcher"
            return super().fetch_translations(instr)

    primary: MemoryFetcher[str, int] = MemoryFetcher({"humans": data["humans"]})
    fetcher = MultiFetcher(primary, Fallback(data), on_source_conflict="ignore")

    assert sorted(fetcher.fetch_all()) == ALL_SOURCES


def test_fetch_all_logs_dispatched_fetchers(data, caplog):
    primary: MemoryFetcher[str, int] = MemoryFetcher(data)
    loser: MemoryFetcher[str, int] = MemoryFetcher({"humans": data["humans"]})
    fetcher = MultiFetcher(primary, loser, on_source_conflict="ignore")

    with caplog.at_level(logging.DEBUG, logger="id_translation.fetching"):
        fetcher.fetch_all()

    counts = [r.num_fetchers for r in caplog.records if hasattr(r, "num_fetchers")]
    assert counts == [1, 1], "the loser has no sources left to fetch"


@pytest.mark.parametrize(
    "sources",
    [
        *combinations(ALL_SOURCES, 1),
        *combinations(ALL_SOURCES, 2),
        *combinations(ALL_SOURCES, 3),
        *combinations(ALL_SOURCES, 4),
    ],
    ids=" + ".join,
)
def test_fetch_all_with_explicit_sources(multi_fetcher, expected, sources):
    sources = set(sources)
    actual = multi_fetcher.fetch_all(sources=sources)
    assert set(actual) == sources

    for source in sources:
        assert actual[source] == expected[source], f"{source=}"


def test_fetch(multi_fetcher: MultiFetcher[str, int], data: dict[str, pd.DataFrame]) -> None:
    required = {"id"}
    placeholders = {"name", "is_nice"}

    sampled = [IdsToFetch(source, set(df.id)) for source, df in data.items()]
    memory_fetcher: MemoryFetcher[str, int] = MemoryFetcher(data)
    expected: SourcePlaceholderTranslations[str] = memory_fetcher.fetch(sampled, placeholders, required=required)
    actual = multi_fetcher.fetch(sampled, placeholders, required=required)

    assert actual == expected


def test_ranks(multi_fetcher, fetchers):
    default_fetcher, empty_fetcher, fallback_fetcher, sql_fetcher = fetchers

    assert len(multi_fetcher.children) == 3
    assert default_fetcher in multi_fetcher.children
    assert empty_fetcher not in multi_fetcher.children
    assert fallback_fetcher in multi_fetcher.children
    assert sql_fetcher in multi_fetcher.children

    assert multi_fetcher._id_to_rank[id(default_fetcher)] == 0
    assert multi_fetcher._id_to_rank[id(fallback_fetcher)] == 2
    assert multi_fetcher._id_to_rank[id(sql_fetcher)] == 3


def test_from_config():
    translator = Translator[str, str, IdTypes].from_config(
        ROOT / "config.imdb.toml",
        extra_fetchers=[ROOT / "transform/fetcher-only.toml"],
    )
    assert sorted(translator.sources) == ["drinking_preferences_bitmask", "guests", "name_basics", "title_basics"]


class TestOptionalFetchers:
    def test_no_crashes_one_optional(self):
        self._run(
            children=[
                CrashFetcher(False, optional=False),
                CrashFetcher(False, optional=True),
            ],
            expected=[0],
        )

    def test_optional_crash(self):
        self._run(
            children=[
                CrashFetcher(False, optional=False),
                CrashFetcher(True, optional=True),
            ],
            expected=[0],
        )

    def test_non_optional_crash(self):
        self._run(
            children=[
                CrashFetcher(True, optional=False),
                CrashFetcher(True, optional=True),
            ],
            expected=None,
        )

    def test_all_optional_crash(self):
        with pytest.warns(FetcherWarning, match="No fetchers"):
            self._run(
                children=[
                    CrashFetcher(True, optional=True),
                    CrashFetcher(True, optional=True),
                ],
                expected=[],
            )

    def test_sql_fetcher_crash(self):
        self._run(
            children=[
                CrashFetcher(False, optional=False),
                SqlFetcher("postgresql+pg8000://bad_user:bad-password@localhost", optional=True),
            ],
            expected=[0],
        )

    def test_unresolved_children_names_the_crash(self):
        """Only children that raised: their sources are unknowable, unlike those that reported none."""
        crashed = CrashFetcher(True, optional=True)
        fetcher: MultiFetcher[str, int] = MultiFetcher(
            CrashFetcher(False, optional=False),
            crashed,
            MemoryFetcher({}, optional=True),  # Discarded for reporting no sources; known to serve nothing.
            on_source_conflict="ignore",
        )

        assert len(fetcher._unresolved_children()) == 1
        assert f"fetcher CrashFetcher at {hex(id(crashed))}" in fetcher._unresolved_children()[0]

    def test_unresolved_children_is_empty_without_discards(self):
        fetcher: MultiFetcher[str, int] = MultiFetcher(
            CrashFetcher(False, optional=False),
            CrashFetcher(False, optional=True),
            on_source_conflict="ignore",
        )

        assert fetcher._unresolved_children() == []

    def test_unresolved_children_includes_nested_multi_fetchers(self):
        """A [transform]-section may outlive a child of a nested MultiFetcher; its crash must be reported too."""
        crashed = CrashFetcher(True, optional=True)
        inner: MultiFetcher[str, int] = MultiFetcher(crashed, MemoryFetcher({"inner": {"id": [1]}}))
        outer: MultiFetcher[str, int] = MultiFetcher(inner, MemoryFetcher({"outer": {"id": [1]}}))

        assert len(outer._unresolved_children()) == 1
        assert f"fetcher CrashFetcher at {hex(id(crashed))}" in outer._unresolved_children()[0]

    @staticmethod
    def _run(children, expected):
        fetcher = MultiFetcher(*children, on_source_conflict="ignore")

        if expected is None:
            with pytest.raises(ValueError, match="I crashed!"):
                fetcher.initialize_sources()
        else:
            fetcher.initialize_sources()
            actual = set(fetcher.children)
            assert len(actual) == len(expected)
            for c in (children[i] for i in expected):
                assert c in actual


class CrashFetcher(MemoryFetcher[str, int]):
    def __init__(self, crash: bool, *, optional: bool):
        super().__init__({"source": {"id": [1]}}, optional=optional)
        self.crash = crash

    def __str__(self) -> str:
        return f"CrashFetcher({self.crash}, optional={self.optional})"

    def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:
        if self.crash:
            raise ValueError("I crashed!")

        return super()._initialize_sources(task_id)


@pytest.mark.filterwarnings("ignore:No fetchers:id_translation.fetching.exceptions.FetcherWarning")
class TestNoSources:
    def test_required(self, caplog):
        fetcher: MultiFetcher[str, int] = MultiFetcher(MemoryFetcher({}, optional=False))
        fetcher.initialize_sources()

        assert len(fetcher.children) == 1

        ends = {
            "does not provide any sources.",
            "but will be kept: All sources found in higher-ranking fetchers.",
        }
        for record in caplog.records:
            message = record.getMessage()
            for end in ends:
                if message.endswith(end):
                    assert message.startswith("Required rank-0")
                    assert record.levelname == "WARNING"
                    assert record.name.endswith("MultiFetcher")
                    ends.remove(end)
                    break

    @pytest.mark.parametrize("level", ["DEBUG", "WARNING"])
    def test_optional(self, caplog, level):
        fetcher: MultiFetcher[str, int] = MultiFetcher(
            MemoryFetcher({}, optional=True), fetcher_discarded_log_level=level
        )
        fetcher.initialize_sources()

        assert len(fetcher.children) == 0

        for record in caplog.records:
            message = record.getMessage()

            if message.startswith("Discarding optional rank-0"):
                assert message.endswith("No sources.")
                assert record.levelname == level
                assert record.name.endswith("MultiFetcher")
                return

        raise AssertionError("no matching record found")


@pytest.mark.filterwarnings("ignore:Discarded:id_translation.fetching.exceptions.DuplicateSourceWarning")
def test_copy(fetchers):
    ids_to_fetch = [IdsToFetch("animals", {1})]

    original = MultiFetcher(*fetchers, on_source_conflict="ignore", max_workers=2)
    original.initialize_sources()
    original_fetch_all = original.fetch_all()
    original_fetch = original.fetch(ids_to_fetch)

    copied = deepcopy(original)
    assert original_fetch_all == copied.fetch_all()
    assert original.placeholders == copied.placeholders

    copied_children = {copied._id_to_rank[id(c)]: id(c) for c in copied.children}
    original_children = {original._id_to_rank[id(c)]: id(c) for c in original.children}

    assert sorted(copied_children) == sorted(original_children), "keys should match"
    assert set(copied_children.values()).isdisjoint(original_children.values()), "IDs should be different"

    assert original_fetch == copied.fetch(ids_to_fetch)

    # Unclosed SQLite connections emit a ResourceWarning whenever the GC gets to them, failing an unrelated test.
    original.close()
    copied.close()


def test_pickle(data):
    """Children are keyed by `id()`, which unpickled children do not keep."""
    original: MultiFetcher[str, int] = MultiFetcher(
        MemoryFetcher[str, int]({"humans": data["humans"]}),
        MemoryFetcher[str, int]({"humans": data["humans"], "animals": data["animals"]}),
        on_source_conflict="ignore",
    )
    copied = pickle.loads(pickle.dumps(original))  # noqa: S301

    assert copied.sources == ["humans", "animals"], "discovery formats the losing child"
    assert [copied.get_sources(child) for child in copied.children] == [["humans"], ["animals"]]
    assert copied.format_child(copied.children[1]).startswith("rank-1")


def test_copy_uncloneable_child_raises(fetchers):
    """A copy that silently shares a child is worse than no copy; Translator.copy() decides what to do instead."""
    original = MultiFetcher(NotCloneableFetcher(), *fetchers, on_source_conflict="ignore")

    with pytest.raises(TypeError, match=r"Cannot clone rank-0 fetcher NotCloneableFetcher\(") as exc_info:
        deepcopy(original)

    assert "pickle 'module'" in str(exc_info.value)


def test_copy_uncloneable_child_leaves_memo_clean(fetchers):
    """A shared memo must not keep the half-built shell, or a later copy would adopt it."""
    original = MultiFetcher(NotCloneableFetcher(), *fetchers, on_source_conflict="ignore")
    memo: dict[int, object] = {}

    with pytest.raises(TypeError):
        deepcopy(original, memo)

    assert memo == {}


def test_init_logging(multi_fetcher, caplog):
    assert len(caplog.records) == 0

    multi_fetcher.initialize_sources(id(test_init_logging))

    def discard_empty_optional(message: str, level: int) -> bool:
        if message.startswith("Discarding optional rank-1 fetcher MemoryFetcher(sources=<no sources>"):
            assert level == logging.DEBUG, "optional => DEBUG"
            assert message.endswith(": No sources.")
            return True

        return False

    def required_no_sources(message: str, level: int) -> bool:
        if message.startswith("Required rank-3 fetcher SqlFetcher('sqlite://')"):
            assert level == logging.WARNING, "required => WARNING"
            assert message.endswith("does not provide any sources.")
            return True

        return False

    def optional_source_outranked(message: str, level: int) -> bool:
        if message.startswith("Discarded source='humans' retrieved from rank-2 fetcher MemoryFetcher"):
            assert level == logging.DEBUG, "optional => DEBUG"
            assert "since the rank-0 fetcher MemoryFetcher(sources=['humans', 'animals']" in message
            assert "already claimed same source." in message
            return True

        return False

    checkers = [
        discard_empty_optional,
        required_no_sources,
        optional_source_outranked,
    ]

    index = 0
    for record in caplog.records:
        if index == len(checkers):
            return  # All checkers done
        if checkers[index](record.getMessage(), record.levelno):
            index += 1

    if index < len(checkers):
        raise AssertionError(f"Did not finish: {index=} | checker={checkers[index - 1]}")


def test_discovery_failure_does_not_escape_the_discard_handler():
    """Formatting a fetcher must not trigger discovery: the handler formats the child it is discarding."""

    class Boom(MemoryFetcher[str, int]):
        def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:
            del task_id
            raise ConnectionError("discovery failed")

    bad = Boom({"a": {"id": [1], "name": ["a"]}}, optional=True)
    good = MemoryFetcher[str, int]({"b": {"id": [1], "name": ["b"]}})

    multi_fetcher = MultiFetcher(bad, good)
    multi_fetcher.initialize_sources()

    assert multi_fetcher.sources == ["b"], "the optional child must be discarded, not re-raise"
    assert "<uninitialized>" in str(bad), "formatting must not attempt discovery either"


def test_discard_after_failed_discovery_does_not_call_str():
    """A custom ``__str__`` may read the public `sources`, which re-runs the discovery that just failed."""

    class Unreachable(MemoryFetcher[str, int]):
        attempts = 0

        def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:  # noqa: ARG002
            self.attempts += 1
            raise ConnectionError("unreachable")

        def __str__(self) -> str:
            return f"Unreachable(sources={self.sources})"

    bad = Unreachable({}, optional=True)
    multi_fetcher = MultiFetcher(MemoryFetcher[str, int]({"b": {"id": [1]}}), bad)
    multi_fetcher.initialize_sources()

    assert multi_fetcher.sources == ["b"]
    assert bad.attempts == 1
    assert multi_fetcher._unresolved_children() == [f"rank-1 fetcher Unreachable at {hex(id(bad))}"]


@pytest.mark.parametrize(
    "error, optional",
    [(ConnectionError("down"), False), (AmbiguousScoreError("tied"), True)],
    ids=["required", "optional-not-suppressed"],
)
def test_raise_after_failed_discovery_does_not_call_str(error, optional):
    """A ``__str__`` that re-runs discovery would replace the original error while the context note is formatted."""

    class Failing(MemoryFetcher[str, int]):
        attempts = 0

        def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:  # noqa: ARG002
            self.attempts += 1
            raise error

        def __str__(self) -> str:
            return f"Failing(sources={self.sources})"

    bad = Failing({}, optional=optional)
    multi_fetcher: MultiFetcher[str, int] = MultiFetcher(bad)

    with pytest.raises(type(error)) as exc_info:
        multi_fetcher.initialize_sources()
    assert exc_info.value is error
    assert bad.attempts == 1
    assert f"child= rank-0 fetcher Failing at {hex(id(bad))}" in "\n".join(exc_info.value.__notes__)


class _Rediscovering(MemoryFetcher[str, int]):
    """Undiscovered until asked: its ``__str__`` reads `sources`, and discovery raises."""

    def __init__(self) -> None:
        super().__init__({})
        self.attempts = 0

    def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:  # noqa: ARG002
        self.attempts += 1
        raise ConnectionError("down")

    def __str__(self) -> str:
        return f"_Rediscovering(sources={self.sources})"

    def close(self) -> None:
        raise RuntimeError("close failed")

    def __deepcopy__(self, memo: dict[int, Any] | None = None) -> Never:
        raise TypeError("cannot be copied")


def test_close_copy_and_repr_do_not_run_discovery_of_children(caplog):
    children = [_Rediscovering(), _Rediscovering()]
    multi_fetcher: MultiFetcher[str, int] = MultiFetcher(*children)

    with pytest.raises(RuntimeError, match="close failed"):
        multi_fetcher.close()
    assert any("Failed to close rank-1 fetcher _Rediscovering at" in r.getMessage() for r in caplog.records)

    with pytest.raises(TypeError, match="Cannot clone rank-0 fetcher _Rediscovering at"):
        deepcopy(multi_fetcher)

    assert "    _Rediscovering,\n" in repr(multi_fetcher)
    assert [child.attempts for child in children] == [0, 0]
    assert "MemoryFetcher(sources=<uninitialized>" in repr(MultiFetcher(MemoryFetcher({}))), "bundled __str__ is safe"


def test_repr_of_plain_and_nested_children():
    """A plain ``Fetcher`` has no discovery state of its own; its ``__str__`` is trusted once the parent is discovered."""

    class Plain(_TestFetcher[str, int]):
        reads = 0

        def __str__(self) -> str:
            self.reads += 1
            return f"Plain(sources={self.sources})"

    plain = Plain(["a"])
    multi_fetcher: MultiFetcher[str, int] = MultiFetcher(plain, MultiFetcher(MemoryFetcher({"b": {"id": [1]}})))

    before = repr(multi_fetcher)
    assert "    Plain,\n" in before
    assert "    MultiFetcher,\n" in before
    assert plain.reads == 0

    multi_fetcher.initialize_sources()
    after = repr(multi_fetcher)
    assert "    Plain(sources=['a']),\n" in after
    assert "    MultiFetcher(max_workers=" in after


def test_subclass_logs_as_its_own_class(caplog):
    class Derived(MultiFetcher[str, int]):
        pass

    caplog.set_level(logging.DEBUG, logger="id_translation")
    Derived(MemoryFetcher({"s": {"id": [1]}})).initialize_sources()

    records = [r for r in caplog.records if r.name.startswith("id_translation.fetching.") and "children" in r.msg]
    assert {r.name for r in records} == {"id_translation.fetching.Derived"}
    assert {(r.fetcher_class, r.fetcher_config_file) for r in records} == {(f"{__name__}.Derived", None)}


def test_conflict_that_raises_logs_the_task_id(caplog):
    fetcher: MultiFetcher[str, int] = MultiFetcher(MemoryFetcher({"s": {"id": [1]}}), MemoryFetcher({"s": {"id": [1]}}))
    with pytest.raises(exceptions.DuplicateSourceError):
        fetcher.initialize_sources(task_id=17)
    assert [(r.task_id, r.source) for r in caplog.records if r.levelno >= logging.ERROR] == [(17, "s")]


def test_fetch_all_debug_extras_are_json_serializable(caplog):
    # The root `VerifyRecord` handler in conftest raises for extras that json.dumps rejects, such as sets.
    caplog.set_level(logging.DEBUG, logger="id_translation")
    fetcher: MultiFetcher[str, int] = MultiFetcher(MemoryFetcher({"s": {"id": [1], "name": ["a"]}}))

    fetcher.fetch_all(("id", "name"), placeholder_attributes={"name": {"upper"}})


def test_fetch_all_error_names_the_child(data):
    class Failing(MemoryFetcher[str, int]):
        def fetch_translations(self, instr):  # noqa: ARG002
            raise ConnectionError("lost")

    fetcher = MultiFetcher(Failing({"humans": data["humans"]}))
    with pytest.raises(ConnectionError, match="lost") as exc_info:
        fetcher.fetch_all()
    assert any(note.startswith("Context (added by MultiFetcher):") for note in exc_info.value.__notes__)


def test_fetch_all_unknown_source_raises(multi_fetcher):
    with pytest.raises(exceptions.UnknownSourceError):
        multi_fetcher.fetch_all(sources={"humans", "no-such-source"})


class _NoIdColumn(MemoryFetcher[str, int]):
    def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:  # noqa: ARG002
        return {"notes": ["title"]}


class _Reentrant(MemoryFetcher[str, int]):
    def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:  # noqa: ARG002
        return {source: [] for source in self.sources}


class _Raises(MemoryFetcher[str, int]):
    def __init__(self, error: Exception) -> None:
        super().__init__({}, optional=True)
        self.error = error

    def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:  # noqa: ARG002
        raise self.error


@pytest.mark.parametrize(
    "child, expected",
    [
        (_NoIdColumn({}, optional=True), exceptions.UnknownIdPlaceholderError),
        (_Reentrant({}, optional=True), exceptions.ImplementationError),
        (_Raises(AmbiguousScoreError("tied")), AmbiguousScoreError),
        (_Raises(exceptions.DuplicateSourceError("both", source="s")), exceptions.DuplicateSourceError),
    ],
    ids=["no-id-column", "reentrant", "mapping", "duplicate-source"],
)
def test_errors_that_escape_optional(child, expected):
    """`optional` covers an unavailable source, not a misconfigured or broken one."""
    fetcher = MultiFetcher(MemoryFetcher({"people": {"id": [1]}}), child)

    with pytest.raises(expected) as exc_info:
        fetcher.initialize_sources()
    assert any("child= rank-1" in note for note in exc_info.value.__notes__), (
        "must name the child, as for a required one"
    )


def test_failed_discovery_is_not_committed(monkeypatch):
    """A raise after discovery started must leave nothing marked as done, or the retry returns a partial result."""
    fetcher: MultiFetcher[str, int] = MultiFetcher(
        MemoryFetcher({"a": {"id": [1]}}),
        MemoryFetcher({"a": {"id": [1]}}),
        on_source_conflict="ignore",
    )

    def raise_error(*_args, **_kwargs):
        raise RuntimeError("raised while handling the outranked child")

    # Raises from the per-child loop, after the first child's sources were collected.
    monkeypatch.setattr("id_translation.fetching._multi_fetcher._log_outranked", raise_error)

    for _ in range(2):
        with pytest.raises(RuntimeError, match="outranked child"):
            fetcher.initialize_sources()


@pytest.mark.parametrize("level", ["DEBUG", "ERROR"])
def test_outranked_optional_discard_uses_the_discard_level(caplog, level):
    data = {"people": {"id": [1]}}
    fetcher: MultiFetcher[str, int] = MultiFetcher(
        MemoryFetcher(data),
        MemoryFetcher(data, optional=True),
        on_source_conflict="ignore",
        fetcher_discarded_log_level=level,
    )
    with caplog.at_level(logging.DEBUG, logger="id_translation"):
        fetcher.initialize_sources()

    (record,) = [r for r in caplog.records if "All sources found in higher-ranking fetchers" in r.getMessage()]
    assert record.levelname == level


@pytest.mark.parametrize("max_workers", [0, -1, "2"])
def test_bad_max_workers_raises_at_construction(max_workers):
    with pytest.raises((ValueError, TypeError)):
        MultiFetcher(max_workers=max_workers)


class _Closing(MemoryFetcher[str, int]):
    def __init__(self, *args, fail_close=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_close = fail_close
        self.closed = False

    def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:  # noqa: ARG002
        raise AssertionError("close() must not run discovery")

    def close(self) -> None:
        self.closed = True
        if self.fail_close:
            raise ConnectionError(f"{self} failed to close")


class TestClose:
    def test_closes_every_child_without_discovery(self, caplog):
        children = [_Closing({}, fail_close=True), _Closing({}), _Closing({}, fail_close=True)]
        fetcher = MultiFetcher(*children)

        with pytest.raises(ConnectionError) as exc_info:
            fetcher.close()
        assert all(child.closed for child in children)
        assert any("child= rank-0" in note for note in exc_info.value.__notes__)
        assert any(r.levelname == "ERROR" and "Failed to close rank-2" in r.getMessage() for r in caplog.records)

    def test_discards_optional_child_that_also_fails_to_close(self, caplog):
        class Down(_Closing):
            def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:  # noqa: ARG002
                raise ConnectionError("down")

        down = Down({}, fail_close=True, optional=True)
        fetcher = MultiFetcher(MemoryFetcher({"people": {"id": [1]}}), down)

        fetcher.initialize_sources()
        assert len(fetcher.children) == 1
        assert down.closed
        assert any("Failed to close discarded rank-1" in r.getMessage() for r in caplog.records)


def test_first_failure_cancels_queued_children(monkeypatch):
    calls = []
    release = threading.Event()

    class Recording(MemoryFetcher[str, int]):
        def __init__(self, name: str, *, fail: bool = False) -> None:
            super().__init__({name: {"id": [1]}})
            self.name = name
            self.fail = fail

        def fetch_translations(self, instr):
            calls.append(self.name)
            if self.fail:
                raise ConnectionError(self.name)
            release.wait(timeout=5)  # Holds the only worker until _gather has handled the failure.
            return super().fetch_translations(instr)

    children = [Recording("first", fail=True), Recording("second"), Recording("third", fail=True)]
    fetcher = MultiFetcher(*children, max_workers=1)

    gather = fetcher._gather

    def gather_then_release(*args, **kwargs):
        try:
            return gather(*args, **kwargs)
        finally:
            release.set()

    monkeypatch.setattr(fetcher, "_gather", gather_then_release)

    with pytest.raises(ConnectionError, match="first"):
        fetcher.fetch([IdsToFetch(name, {1}) for name in ("first", "second", "third")])
    assert "third" not in calls


class Leaky(MemoryFetcher[str, int]):
    def fetch(self, *args, **kwargs):
        rv = super().fetch(*args, **kwargs)
        return {**rv, "b": PlaceholderTranslations("b", ("id",), [(-1,)])}

    def fetch_all(self, *args, **kwargs):
        rv = super().fetch_all(*args, **kwargs)
        return {**rv, "b": PlaceholderTranslations("b", ("id",), [(-1,)])}


@pytest.mark.parametrize("leaky_rank", [0, 1])
@pytest.mark.parametrize("max_workers", [1, 3])
@pytest.mark.parametrize("fetch_all", [False, True])
def test_only_the_serving_child_is_kept(leaky_rank, max_workers, fetch_all):
    children: list[MemoryFetcher[str, int]] = [MemoryFetcher({"b": {"id": [1]}})]
    children.insert(leaky_rank, Leaky({"a": {"id": [1]}}))
    fetcher = MultiFetcher(*children, max_workers=max_workers)
    fetcher.initialize_sources()

    with pytest.warns(exceptions.DuplicateSourceWarning, match=f"returned by the rank-{leaky_rank}"):
        if fetch_all:
            result = fetcher.fetch_all()
        else:
            result = fetcher.fetch([IdsToFetch("a", {1}), IdsToFetch("b", {1})])
    assert list(result["b"].records) == [(1,)]


def test_reentrant_discovery():
    class ReadsParent(MemoryFetcher[str, int]):
        def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:
            assert parent.sources  # Re-enters the parent's discovery from the same thread.
            return super()._initialize_sources(task_id)

    parent: MultiFetcher[str, int] = MultiFetcher(ReadsParent({"people": {"id": [1]}}))
    with pytest.raises(exceptions.ImplementationError, match=r"MultiFetcher.initialize_sources\(\) was called during"):
        parent.initialize_sources()
