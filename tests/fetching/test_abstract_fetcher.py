import pickle
import re
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from rics.collections.dicts import InheritedKeysDict

from id_translation.fetching import AbstractFetcher, CacheAccess, MemoryFetcher, MultiFetcher, exceptions
from id_translation.fetching.exceptions import CacheAccessNotAvailableError
from id_translation.fetching.types import FetchInstruction, IdsToFetch, PartialCacheHit
from id_translation.mapping import Mapper
from id_translation.mapping.exceptions import MappingWarning, UnmappedValuesWarning
from id_translation.offline.types import PlaceholderTranslations


@pytest.fixture(scope="module")
def fetcher(data):
    return MemoryFetcher(data)


def test_unknown_sources(fetcher):
    with pytest.raises(exceptions.UnknownSourceError, match="edible_humans") as ec:
        fetcher.fetch([IdsToFetch("humans", {1, 2}), IdsToFetch("edible_humans", {1, 2})])
    assert ec.value.unknown_sources == ("edible_humans",)

    with pytest.raises(exceptions.UnknownSourceError, match="edible_humans") as ec:
        fetcher.map_placeholders("edible_humans", placeholders=["not-used"])
    assert ec.value.unknown_sources == ("edible_humans",)


def test_fetch_all_forbidden(data):
    fetcher: MemoryFetcher[str, int] = MemoryFetcher(data, allow_fetch_all=False)
    match = re.escape("Operation 'FETCH_ALL' is not permitted by MemoryFetcher.")
    with pytest.raises(exceptions.ForbiddenOperationError, match=match):
        fetcher.fetch_all()


def test_unknown_placeholders(fetcher):
    with pytest.raises(exceptions.UnknownPlaceholderError, match=r"\['number_of_legs'\] not recognized"):
        fetcher.fetch([IdsToFetch("humans", set())], ("id", "number_of_legs"), required={"number_of_legs"})


def test_missing_id_placeholder_raises_clear_error():
    # "id" is required implicitly even when not requested; a source that never maps it must raise
    # UnknownPlaceholderError rather than translate by whichever column happens to be last.
    no_id_fetcher: MemoryFetcher[str, str] = MemoryFetcher({"countries": {"code": ["US"], "name": ["USA"]}})
    with pytest.raises(exceptions.UnknownPlaceholderError, match=r"\['id'\] not recognized"):
        no_id_fetcher.fetch([IdsToFetch("countries", {"US"})])


@pytest.mark.parametrize(
    "selective_fetch_all, required, expected",
    [
        (True, ("id", "name"), {"animals", "humans"}),
        (False, (), {"animals", "humans", "big_table", "huge_table"}),
    ],
)
def test_selective_fetch_all(data, selective_fetch_all, required, expected):
    with pytest.warns(MappingWarning, match="on_unmapped='raise'"):
        fetcher: AbstractFetcher[str, int] = MemoryFetcher(
            data,
            selective_fetch_all=selective_fetch_all,
            mapper=Mapper("equality", on_unmapped="raise"),
        )
    assert set(fetcher.fetch_all(required=required)) == expected


def test_test_crashes_with_selective_fetch_all_disabled(data):
    with pytest.raises(exceptions.UnknownPlaceholderError):
        MemoryFetcher(data, selective_fetch_all=False).fetch_all(required=("id", "name"))


class TestCache:
    def test_from_cache(self, windows_hack_temp_dir):
        fetcher = CachingFetcher(windows_hack_temp_dir)
        self._run(fetcher)

    @pytest.mark.parametrize("clone", [lambda f: f, deepcopy, lambda f: pickle.loads(pickle.dumps(f))])  # noqa: S301
    def test_no_access(self, clone):
        with pytest.raises(CacheAccessNotAvailableError, match=r"documentation/examples/caching/on_disk.html"):
            _ = clone(MemoryFetcher({})).cache_access

    def test_clone(self, windows_hack_temp_dir):
        original = CachingFetcher(windows_hack_temp_dir)

        copy = deepcopy(original)
        assert id(original) != id(copy)
        assert id(original.cache_access) != id(copy.cache_access)
        assert id(original.calls) != id(copy.calls)

        assert id(original.cache_access.parent) == id(original)
        assert id(copy.cache_access.parent) == id(copy)

        self._run(original)
        self._run(copy)

    @staticmethod
    def _run(fetcher: "CachingFetcher") -> None:
        ids_to_fetch = [IdsToFetch("people", {1999})]
        expected = {"people": PlaceholderTranslations("people", ("id", "name"), ((1999, "Sofia"),))}

        calls = fetcher.calls

        assert calls == {"store": 0, "load": 0, "fetch": 0}

        # Initial store. We get one load-attempt (which returns None) followed by a store.
        assert fetcher.fetch_all() == expected
        assert calls == {"store": 1, "load": 1, "fetch": 1}

        # Subsequent calls are loaded from cache, but does not restore it.
        assert fetcher.fetch_all() == expected
        assert calls == {"store": 1, "load": 2, "fetch": 1}

        # Including (and especially) regular data requests
        assert fetcher.fetch(ids_to_fetch) == expected
        assert calls == {"store": 1, "load": 3, "fetch": 1}

        # Clear the cache.
        assert isinstance(fetcher.cache_access, StoreFetchAllCacheAccess)
        fetcher.cache_access.reset()

        assert fetcher.fetch(ids_to_fetch) == expected
        assert calls == {"store": 1, "load": 4, "fetch": 2}


class StoreFetchAllCacheAccess(CacheAccess[str, int]):
    def __init__(self, root: Path, calls: dict[str, int]) -> None:
        super().__init__()
        self._root = root
        self._calls = calls
        self._cache: PlaceholderTranslations[str] | None = None

    def reset(self) -> None:
        self._cache = None

    def store(self, instr: FetchInstruction[str, int], translations: PlaceholderTranslations[str]) -> None:
        assert instr.source == "people"
        if instr.ids is not None:
            return

        self._calls["store"] += 1
        self._cache = translations

    def load(self, instr: FetchInstruction[str, int]) -> PlaceholderTranslations[str] | None:
        assert instr.source == "people"
        self._calls["load"] += 1
        return self._cache


class CachingFetcher(MemoryFetcher[str, int]):
    def __init__(self, windows_hack_temp_dir):
        self.calls = {"store": 0, "load": 0, "fetch": 0}
        super().__init__(
            data={"people": {1999: "Sofia"}},
            return_all=True,
            cache_access=StoreFetchAllCacheAccess(windows_hack_temp_dir, self.calls),
        )

    @property
    def cache_enabled(self) -> bool:
        return True

    def fetch_translations(self, instr):
        self.calls["fetch"] += 1
        return super().fetch_translations(instr)


class TestBadImplementation:
    def test_initialize_sources(self):
        fetcher = BadFetcher()
        match = r"test_abstract_fetcher\.BadFetcher\._initialize_sources\(\) returned None"
        with pytest.raises(exceptions.ImplementationError, match=match):
            fetcher.initialize_sources()

    def test_fetch(self):
        fetcher = BadFetcher()
        match = r"test_abstract_fetcher\.BadFetcher\._initialize_sources\(\) returned None"
        with pytest.raises(exceptions.ImplementationError, match=match):
            fetcher.fetch([IdsToFetch("source", {1})])

    def test_id_column(self):
        fetcher = BadFetcher()
        assert fetcher.id_column("source", candidates=[]) is None


class BadFetcher(AbstractFetcher[str, int]):
    def _initialize_sources(self, _):
        return None

    def fetch_translations(self, instr):
        raise NotImplementedError


def test_concurrent_initialize_sources_warns():
    """Most likely site (I think?) where id-translation-project users might run into this."""

    fetcher = BlockingFetcher()
    errors: list[BaseException] = []

    def call() -> None:
        try:
            fetcher.initialize_sources()
        except BaseException as e:
            errors.append(e)

    first = threading.Thread(target=call, name="first")
    first.start()
    assert fetcher.entered.wait(timeout=5), f"{first=} did not enter"

    # The first thread is now stuck in the critical section. The second thread
    # should detect this and emit a warning.

    second = threading.Thread(target=call, name="second")
    second.start()
    second.join(timeout=5)

    fetcher.release.set()  # Allow the first thread to continue.
    first.join(timeout=5)

    assert len(errors) == 1
    warning = errors[0]
    assert isinstance(warning, exceptions.ConcurrentOperationWarning)
    assert warning.operation == "initialize_sources"
    assert warning.fetcher_class.endswith("test_abstract_fetcher.BlockingFetcher")


class BlockingFetcher(AbstractFetcher[str, int]):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def _initialize_sources(self, _):
        self.entered.set()
        assert self.release.wait(timeout=5)
        return {}

    def fetch_translations(self, instr):
        raise NotImplementedError


class RecordingFetcher(MemoryFetcher[str, int]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instructions: list[FetchInstruction[str, int]] = []

    def fetch_translations(self, instr):
        self.instructions.append(instr)
        return super().fetch_translations(instr)


@pytest.mark.parametrize("overrides", [{}, {"name": "title"}])
def test_instruction_has_only_source_placeholders(overrides):
    label = overrides.get("name", "name")
    fetcher = RecordingFetcher({"people": {"id": [1], label: ["Ada"]}}, mapper=Mapper("equality", overrides=overrides))

    fetcher.fetch([IdsToFetch("people", {1})], ("id", "name", "nickname"), required={"name"})

    (instr,) = fetcher.instructions
    assert instr.placeholders == ("id", label)
    assert instr.required == {"id", label}


def _shared_override_to_absent_column() -> Mapper[str, str, str]:
    # Tests using this add a source with the column: initialize_sources() raises if no source has it.
    return Mapper("equality", overrides=InheritedKeysDict(default={"name": "nope"}))


_HAS_NOPE = {"other": {"id": [1], "nope": ["x"]}}


def test_instruction_drops_override_to_absent_column():
    data = {"people": {"id": [1], "name": ["Ada"]}, **_HAS_NOPE}
    fetcher = RecordingFetcher(data, mapper=_shared_override_to_absent_column())
    fetcher.fetch([IdsToFetch("people", {1})], ("id", "name"))

    (instr,) = fetcher.instructions
    assert instr.placeholders == ("id",)
    assert instr.required == {"id"}


@pytest.mark.parametrize("overrides, column", [({"name": "id"}, "id"), ({"id": "code", "name": "code"}, "code")])
def test_wanted_names_sharing_a_column(overrides, column):
    fetcher = RecordingFetcher({"tags": {column: [1, 2]}}, mapper=Mapper("equality", overrides=overrides))

    (translations,) = fetcher.fetch([IdsToFetch("tags", {1, 2})], ("id", "name"), required={"name"}).values()

    (instr,) = fetcher.instructions
    assert instr.placeholders == (column,)
    assert translations.placeholders == ("id",)
    assert translations.placeholder_aliases["name"] == "id"


def test_wanted_names_sharing_a_column_partial_cache_hit():
    class PartialCache(CacheAccess[str, int]):
        def load(self, instr: FetchInstruction[str, int]) -> PartialCacheHit[str, int]:
            return PartialCacheHit(PlaceholderTranslations(instr.source, ("id",), [(1,)]))

        def store(self, instr: FetchInstruction[str, int], translations: PlaceholderTranslations[str]) -> None:
            pass

    fetcher: MemoryFetcher[str, int] = MemoryFetcher(
        {"tags": {"id": [1, 2]}}, mapper=Mapper("equality", overrides={"name": "id"}), cache_access=PartialCache()
    )

    (translations,) = fetcher.fetch([IdsToFetch("tags", {1, 2})], ("id", "name"), required={"name"}).values()
    assert sorted(map(tuple, translations.records)) == [(1,), (2,)]
    assert translations.placeholder_aliases["name"] == "id"


def test_wanted_name_override_wins_over_a_returned_column_of_its_name():
    data = {"tags": {"id": [1, 2], "name": ["real-one", "real-two"]}}
    fetcher: MemoryFetcher[str, int]
    fetcher = MemoryFetcher(data, return_all=True, mapper=Mapper("equality", overrides={"name": "id"}))

    (translations,) = fetcher.fetch([IdsToFetch("tags", {1, 2})], ("id", "name")).values()
    assert translations.placeholders == ("id",)
    assert translations.placeholder_aliases["name"] == "id"


def test_override_to_absent_column_raises_before_fetching():
    data = {"people": {"id": [1], "name": ["Ada"]}, **_HAS_NOPE}
    fetcher = RecordingFetcher(data, mapper=_shared_override_to_absent_column())
    with pytest.raises(exceptions.UnknownPlaceholderError) as ec:
        fetcher.fetch([IdsToFetch("people", {1})], ("id", "name"), required={"name"})

    assert ec.value.missing_placeholders == ("name",)
    assert fetcher.instructions == []
    notes = "\n".join(ec.value.__notes__)
    assert "override configuration" in notes
    assert "Make shared overrides that 'people' cannot satisfy source-specific." in notes
    assert "did not return" not in notes


def test_unlisted_required_placeholder_is_checked_after_fetching():
    class Unlisted(RecordingFetcher):
        """Lists only id and name, but returns every column."""

        def _initialize_sources(self, task_id):  # noqa: ARG002
            return {"people": ["id", "name"]}

    data = {"people": {"id": [1], "name": ["Ada"], "team": ["sales"]}}
    fetcher = Unlisted(data, mapper=Mapper("equality"), return_all=True)
    (translations,) = fetcher.fetch([IdsToFetch("people", {1})], ("id", "team"), required={"team"}).values()
    assert "team" in translations.placeholders

    listed = RecordingFetcher({"people": {"id": [1], "name": ["Ada"]}}, mapper=Mapper("equality"))
    with pytest.raises(exceptions.UnknownPlaceholderError) as ec:
        listed.fetch([IdsToFetch("people", {1})], ("id", "team"), required={"team", "dept"})
    assert ec.value.missing_placeholders == ("dept", "team")
    assert len(listed.instructions) == 1


def test_attributes_only_for_instruction_placeholders():
    data = {"people": {"id": [1], "name": ["Ada"], "title": ["Dr"]}, **_HAS_NOPE}
    fetcher = RecordingFetcher(data, mapper=_shared_override_to_absent_column())
    attributes = {"name": {"a"}, "title": {"b"}, "nickname": {"c"}}
    fetcher.fetch([IdsToFetch("people", {1})], ("id", "name", "title", "nickname"), placeholder_attributes=attributes)

    (instr,) = fetcher.instructions
    assert instr.placeholders == ("id", "title")
    assert instr.placeholder_attributes == {"title": {"b"}}


def test_selective_fetch_all_skips_source_with_override_to_absent_column():
    data = {"people": {"id": [1], "nick": ["Ada"]}, "dogs": {"id": [1], "name": ["Rex"]}}
    overrides: InheritedKeysDict[str, str, str] = InheritedKeysDict(default={"name": "nick"})
    fetcher = RecordingFetcher(data, mapper=Mapper("equality", overrides=overrides), allow_fetch_all=True)

    fetcher.initialize_sources()  # Silent: 'people' has the column.
    assert sorted(fetcher.fetch_all(("id", "name"), required=("name",))) == ["people"]


@pytest.mark.parametrize("default", [{}, {"name": "nope"}], ids=["specific", "specific-equals-default"])
def test_source_specific_override_to_absent_column_raises_at_initialize_sources(default):
    overrides = InheritedKeysDict(specific={"people": {"name": "nope"}}, default=default)
    fetcher = RecordingFetcher({"people": {"id": [1], "name": ["Ada"]}}, mapper=Mapper("equality", overrides=overrides))

    with pytest.raises(exceptions.UnknownPlaceholderError, match=r"\['nope'\] not recognized") as ec:
        fetcher.initialize_sources()
    hint = (
        "Hint: The overrides {'name': 'nope'} for 'people' name placeholders that it does not have."
        " Correct the column names, or remove the overrides."
    )
    assert ec.value.__notes__ == [hint]


@pytest.mark.parametrize("overrides", [{"name": "nope"}, InheritedKeysDict(default={"name": "nope"})])
def test_shared_override_to_column_no_source_has_raises(overrides):
    data = {"people": {"id": [1], "name": ["Ada"]}, "dogs": {"id": [1], "name": ["Rex"]}}
    fetcher = RecordingFetcher(data, mapper=Mapper("equality", overrides=overrides))

    with pytest.raises(exceptions.UnknownPlaceholderError, match=r"\['nope'\] not recognized") as ec:
        fetcher.initialize_sources()
    assert ec.value.__notes__ == ["Hint: The shared override 'name' -> 'nope' names a placeholder that no source has."]


def test_optional_child_with_bad_override_is_not_discarded():
    bad: MemoryFetcher[str, int] = MemoryFetcher(
        {"dogs": {"id": [1], "name": ["Rex"]}},
        mapper=Mapper("equality", overrides=InheritedKeysDict(specific={"dogs": {"name": "nope"}})),
        optional=True,
    )
    fetcher = MultiFetcher(MemoryFetcher({"people": {"id": [1], "name": ["Ada"]}}), bad)

    with pytest.raises(exceptions.UnknownPlaceholderError, match=r"\['nope'\] not recognized"):
        fetcher.initialize_sources()


@pytest.mark.parametrize("partial", [False, True])
def test_blocked_column_from_cache_is_dropped(partial):
    class StaleCache(CacheAccess[str, int]):
        # Written before the block was added.
        def load(self, instr: FetchInstruction[str, int]) -> Any:
            cached = PlaceholderTranslations(instr.source, ("id", "name", "title"), [(1, "Ada", "Dr")])
            return PartialCacheHit(cached) if partial else cached

        def store(self, instr: FetchInstruction[str, int], translations: PlaceholderTranslations[str]) -> None:
            pass

    data = {"people": {"id": [1, 2], "name": ["Ada", "Bob"], "title": ["Dr", "Mr"]}}
    mapper: Mapper[str, str, str] = Mapper("equality", overrides={"title": "_"})
    fetcher = MemoryFetcher(data, return_all=True, mapper=mapper, cache_access=StaleCache())

    ids = {1, 2} if partial else {1}
    (translations,) = fetcher.fetch([IdsToFetch("people", ids)], ("id", "name", "title")).values()
    assert translations.placeholders == ("id", "name")


def test_required_placeholder_outside_placeholders_is_checked_after_fetching():
    fetcher = RecordingFetcher({"people": {"id": [1], "name": ["Ada"]}}, mapper=Mapper("equality"), return_all=True)

    (translations,) = fetcher.fetch([IdsToFetch("people", {1})], ("id",), required={"name"}).values()

    assert "name" in translations.placeholders


def test_unmapped_required_placeholder_is_mapped_once():
    fetcher = RecordingFetcher({"people": {"id": [1], "name": ["Ada"]}}, mapper=Mapper("equality", on_unmapped="warn"))

    with pytest.warns(UnmappedValuesWarning) as record, pytest.raises(exceptions.UnknownPlaceholderError):
        fetcher.fetch([IdsToFetch("people", {1})], ("id", "nickname"), required={"nickname"})

    assert len([w for w in record if issubclass(w.category, UnmappedValuesWarning)]) == 1


class _NoInitCache(CacheAccess[str, int]):
    def __init__(self) -> None:  # No super().__init__(), as in a dataclass.
        pass

    def store(self, instr: FetchInstruction[str, int], translations: PlaceholderTranslations[str]) -> None:
        pass

    def load(self, instr: FetchInstruction[str, int]) -> None:  # noqa: ARG002
        return None


class TestCacheAccessParent:
    def test_without_super_init(self):
        cache = _NoInitCache()
        with pytest.raises(RuntimeError, match="has no parent fetcher yet"):
            _ = cache.parent

        fetcher = MemoryFetcher({"s": {"id": [1]}}, cache_access=cache)
        assert cache.parent is fetcher

    def test_shared_instance_raises(self):
        cache = _NoInitCache()
        MemoryFetcher({"s": {"id": [1]}}, cache_access=cache)

        with pytest.raises(RuntimeError, match="already belongs to") as exc_info:
            MemoryFetcher({"s": {"id": [1]}}, cache_access=cache)
        assert exc_info.value.__notes__ == ["Hint: Give each fetcher its own CacheAccess instance."]


@pytest.mark.parametrize("call", ["fetch", "fetch_all", "fetch_all_mixed"])
def test_unknown_source_raises_on_a_fresh_fetcher(call):
    fetcher: MemoryFetcher[str, int] = MemoryFetcher({"people": {"id": [1], "name": ["Ada"]}})

    with pytest.raises(exceptions.UnknownSourceError):
        if call == "fetch":
            fetcher.fetch([IdsToFetch("nope", {1})])
        else:
            fetcher.fetch_all(sources={"nope", "people"} if call == "fetch_all_mixed" else {"nope"})


@pytest.mark.parametrize("hook", ["default_mapper_kwargs", "default_score_function"])
def test_overriding_a_removed_public_hook_raises(hook):
    with pytest.raises(TypeError, match=f"overrides \\['{hook}'\\], which are private"):
        type("LegacyFetcher", (MemoryFetcher,), {hook: classmethod(lambda *_: None)})


def test_repeated_source_in_ids_to_fetch_raises():
    fetcher: MemoryFetcher[str, int] = MemoryFetcher({"a": {"id": [1, 2], "name": ["x", "y"]}})
    with pytest.raises(ValueError, match=r"Repeated sources in ids_to_fetch: \['a'\]"):
        fetcher.fetch([IdsToFetch("a", {1}), IdsToFetch("a", {2})])


def test_partial_hit_coverage_with_uuid_heuristics():
    """Requests are UUIDs with heuristics on; rows hold the source's str IDs. A cached row must still cover its ID."""
    uuid = "550e8400-e29b-41d4-a716-446655440000"

    class StrKeyedCache(CacheAccess[str, Any]):
        def __init__(self) -> None:
            super().__init__()
            self.rows: dict[str, tuple[Any, ...]] = {}
            self.layout: tuple[str, ...] = ()

        def load(self, instr: FetchInstruction[str, Any]) -> PartialCacheHit[str, Any] | None:
            if instr.ids is None or not self.layout:
                return None
            records = [self.rows[str(i)] for i in instr.ids if str(i) in self.rows]  # Normalises its own lookup.
            return PartialCacheHit(PlaceholderTranslations(instr.source, self.layout, records))

        def store(self, instr: FetchInstruction[str, Any], translations: PlaceholderTranslations[str]) -> None:  # noqa: ARG002
            self.layout = translations.placeholders
            for row in translations.records:
                self.rows[str(row[self.layout.index("id")])] = tuple(row)

    calls = []

    class Counting(MemoryFetcher[str, Any]):
        def fetch_translations(self, instr: FetchInstruction[str, Any]) -> PlaceholderTranslations[str]:
            calls.append(instr.ids)
            return super().fetch_translations(instr)

    fetcher = Counting({"things": {"id": [uuid], "name": ["found"]}}, cache_access=StrKeyedCache())
    for _ in range(3):
        fetcher.fetch([IdsToFetch("things", {UUID(uuid)})], ("id", "name"), enable_uuid_heuristics=True)
    assert len(calls) == 1, "the cached row covers the UUID request"


def test_fetch_all_does_not_change_the_shared_mapper():
    """Other threads use the instance while fetch_all runs; only the call itself may relax unmapped handling."""
    seen = []

    class Recording(MemoryFetcher[str, int]):
        def fetch_translations(self, instr: FetchInstruction[str, int]) -> PlaceholderTranslations[str]:
            seen.append((self.mapper.on_unmapped, deepcopy(self).mapper.on_unmapped))  # As a concurrent copy() would.
            return super().fetch_translations(instr)

    mapper: Mapper[str, str, str] = Mapper("equality", on_unmapped="warn")
    fetcher = Recording({"people": {"id": [1], "name": ["Ada"]}}, mapper=mapper)
    fetcher.fetch_all(["id", "name", "nickname"])  # 'nickname' is unmapped, which fetch_all() ignores.

    assert seen == [("warn", "warn")]


def test_on_disk_cache_example_rejects_data_without_a_requested_placeholder(tmp_path, monkeypatch):
    import importlib.util

    from id_translation import Translator

    from ..conftest import ROOT

    spec = importlib.util.spec_from_file_location(
        "on_disk", ROOT.parent / "docs/documentation/examples/caching/on_disk.py"
    )
    assert spec is not None and spec.loader is not None
    on_disk = importlib.util.module_from_spec(spec)
    monkeypatch.setattr("builtins.print", lambda *_, **__: None)
    spec.loader.exec_module(on_disk)

    data = {"people": {"id": [1904], "name": ["Fred"], "email": ["fred@x"]}}

    def create() -> Translator[str, str, int]:
        return Translator(MemoryFetcher(data, cache_access=on_disk.MyCacheAccess(root=str(tmp_path), ttl=3600)))

    create().go_offline()  # Stores the default format's placeholders: 'id' and 'name'.
    assert create().translate(1904, "people", fmt="{id}:{name}[ <{email}>]") == "1904:Fred <fred@x>"


@pytest.mark.parametrize("bundled", [True, False])
def test_missing_id_column_hint_for_implementers(bundled):
    cls = MemoryFetcher if bundled else type("MyFetcher", (MemoryFetcher,), {})
    fetcher = cls({"audit_log": {"event": ["login"]}})

    with pytest.raises(exceptions.UnknownIdPlaceholderError) as exc_info:
        fetcher.initialize_sources()
    leave_out = [n for n in exc_info.value.__notes__ if "leave it out of MyFetcher._initialize_sources()" in n]
    assert bool(leave_out) is not bundled
