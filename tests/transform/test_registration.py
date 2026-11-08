"""Tests for transformers owned by the ``Translator``; see ``Translator.register_transformer``."""

import gc
import logging
import pickle
import threading
import warnings
import weakref
from collections.abc import MutableMapping
from copy import copy as shallow_copy
from copy import deepcopy

import pytest

from id_translation import Translator
from id_translation.exceptions import TransformerConflictError, TransformerStateError, TranslationWarning
from id_translation.fetching import MemoryFetcher, MultiFetcher
from id_translation.testing import TestFetcher as _TestFetcher  # Aliased: pytest collects Test* classes
from id_translation.transform import BitmaskTransformer, TransformerStack
from id_translation.transform.types import Transformer

from .conftest import DATA, Marker, make_translator, translate

HINT = (
    "Hint: Register before the transformers settle, or copy with the full set: "
    "translator.copy(transformers={{**translator.transformers, {source}: ...}})."
)


class _RaisingFetcher(MemoryFetcher[str, int]):
    """Constructs fine and fails during source discovery -- what `optional=true` is for."""

    recovered = False

    def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:
        if self.recovered:
            return super()._initialize_sources(task_id)
        raise ValueError(f"no connection (task_id={task_id})")


class _EmptyFetcher(MemoryFetcher[str, int]):
    """Reports no sources, so it is known to serve none."""

    def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:  # noqa: ARG002
        return {}


class _RaisingProvider(MemoryFetcher[str, int]):
    """Discovers its sources fine, then fails when asked to provide a transformer for one of them."""

    recovered = False

    def get_transformer(self, source: str) -> Transformer[int] | None:
        if source == "boom" and not self.recovered:
            raise ValueError("provider is down")
        return Marker(f"provided-{source}")


def _unpickle(translator: Translator[str, str, int]) -> Translator[str, str, int]:
    revived: Translator[str, str, int] = pickle.loads(pickle.dumps(translator))  # noqa: S301
    return revived


@pytest.mark.parametrize("how", ["init", "method"])
def test_registration(how):
    transformer = Marker("x")
    translator = make_translator(how, {"bitmasks": transformer})

    assert translator._tx._transformers == {"bitmasks": transformer}
    assert translator._tx._transformers["bitmasks"] is transformer
    assert translate(translator) == "1:one|x"


class TestReadOnlyView:
    @pytest.fixture
    def translator(self) -> Translator[str, str, int]:
        return Translator(MemoryFetcher(DATA), transformers={"bitmasks": Marker("x")})

    def test_is_live(self, translator):
        view = translator._tx._transformers
        translator.register_transformer("other", Marker("y"))
        assert view.keys() == {"bitmasks", "other"}, "should reflect later registrations"

    def test_mutation_raises(self, translator):
        translator.initialize_sources(settle_transformers=True)
        with pytest.raises(TypeError):
            translator.transformers["other"] = Marker("y")


class TestSequenceNormalization:
    @pytest.mark.parametrize("how", ["init", "method"])
    def test_chain_becomes_a_stack(self, how):
        first, second = Marker("first"), Marker("second")
        translator = make_translator(how, {"bitmasks": [first, second]})

        stack = translator._tx._transformers["bitmasks"]
        assert isinstance(stack, TransformerStack)
        assert stack.transformers == (first, second), "members must keep the given order"
        assert translate(translator) == "1:one|first|second"

    def test_single_element_unwraps(self):
        transformer = Marker("x")
        translator = make_translator("method", {"bitmasks": [transformer]})

        assert translator._tx._transformers["bitmasks"] is transformer

    @pytest.mark.parametrize("how", ["init", "method"])
    def test_empty_raises(self, how):
        with pytest.raises(ValueError, match="empty"):
            make_translator(how, {"bitmasks": []})

    @pytest.mark.parametrize("bad", ["oops", "", b"oops", b"", bytearray(b"oops"), 42, None, set()])
    def test_non_transformer_raises(self, bad):
        """Anchored: a `str` chained as a Sequence would report "Element 0 ..." and pass an unanchored match."""
        with pytest.raises(TypeError, match=r"^Transformer must implement the Transformer protocol"):
            make_translator("method", {"bitmasks": bad})

    def test_sequence_transformer_is_not_read_as_a_chain(self):
        class SequenceMarker(tuple[int, ...], Transformer[int]):
            __slots__ = ()

            def update_ids(self, ids: set[int], /) -> None: ...

            def update_translations(self, translations: dict[int, str], /) -> None:
                for key in translations:
                    translations[key] += "|seq"

            def try_add_missing_key(self, key: int, /, *, translations: MutableMapping[int, str]) -> None: ...

        transformer = SequenceMarker([1, 2, 3])
        translator = make_translator("method", {"bitmasks": transformer})

        assert translator._tx._transformers["bitmasks"] is transformer
        assert translate(translator) == "1:one|seq"

    def test_falsy_transformer_is_fully_applied(self):
        """A Sequence-implementing transformer may be empty, and must not be skipped by a truthiness check."""

        class FalsyMarker(Marker, tuple[str, ...]):
            __slots__ = ()

            def __new__(cls, tag: str) -> "FalsyMarker":
                del tag  # An empty tuple, so the instance is falsy.
                return super().__new__(cls)

            def try_add_missing_key(self, key: int, /, *, translations: MutableMapping[int, str]) -> None:
                translations[key] = f"made-up-{key}"

        translator = make_translator("method", {"bitmasks": FalsyMarker("x")})

        assert not translator._tx._transformers["bitmasks"], "precondition: the transformer is falsy"
        assert translate(translator) == "1:one|x", "update_translations() must run"
        assert translate(translator, idx=99) == "made-up-99", "try_add_missing_key() must run too"

    @pytest.mark.parametrize("how", ["init", "method"])
    def test_class_is_not_an_instance(self, how):
        """`isinstance` against a runtime-checkable Protocol also accepts the class; a forgotten `()` must not pass."""
        with pytest.raises(TypeError, match=r"must be an instance, got the BitmaskTransformer class"):
            make_translator(how, {"bitmasks": BitmaskTransformer})  # type: ignore[dict-item]

    def test_class_in_a_chain_is_not_an_instance(self):
        with pytest.raises(TypeError, match=r"Element 1 of the transformer chain must be an instance"):
            make_translator("method", {"bitmasks": [Marker("x"), BitmaskTransformer]})  # type: ignore[list-item]

    def test_bad_element_names_its_position_and_type(self):
        """The element's type, not the sequence's."""
        with pytest.raises(TypeError, match=r"Element 1 of the transformer chain .*, got str\."):
            make_translator("method", {"bitmasks": [Marker("x"), "oops"]})  # type: ignore[list-item]


class TestOnExisting:
    @pytest.fixture
    def translator(self) -> Translator[str, str, int]:
        return Translator(MemoryFetcher(DATA), transformers={"bitmasks": Marker("old")})

    def test_default_raises(self, translator):
        with pytest.raises(TransformerConflictError, match="bitmasks"):
            translator.register_transformer("bitmasks", Marker("new"))

    def test_raise_keeps_the_old_one(self, translator):
        old = translator._tx._transformers["bitmasks"]
        with pytest.raises(ValueError, match="already registered"):
            translator.register_transformer("bitmasks", Marker("new"))
        assert translator._tx._transformers["bitmasks"] is old

    def test_append(self, translator):
        old = translator._tx._transformers["bitmasks"]
        new = Marker("new")
        translator.register_transformer("bitmasks", new, on_existing="append")

        stack = translator._tx._transformers["bitmasks"]
        assert isinstance(stack, TransformerStack)
        assert stack.transformers == (old, new), "the existing transformer runs first"
        assert translate(translator) == "1:one|old|new"

    def test_append_flattens(self, translator):
        old = translator._tx._transformers["bitmasks"]
        first, second = Marker("first"), Marker("second")
        translator.register_transformer("bitmasks", [first, second], on_existing="append")

        stack = translator._tx._transformers["bitmasks"]
        assert isinstance(stack, TransformerStack)
        assert stack.transformers == (old, first, second)

    def test_append_to_unregistered_source(self, translator):
        transformer = Marker("x")
        translator.register_transformer("other", transformer, on_existing="append")
        assert translator._tx._transformers["other"] is transformer

    def test_overwrite(self, translator):
        new = Marker("new")
        translator.register_transformer("bitmasks", new, on_existing="overwrite")

        assert translator._tx._transformers["bitmasks"] is new
        assert translate(translator) == "1:one|new"

    def test_bad_value_raises(self, translator):
        with pytest.raises(TypeError, match="on_existing"):
            translator.register_transformer("bitmasks", Marker("new"), on_existing="APPEND")


def test_register_from_discovered_sources():
    data = {
        "flags_bitmask": {"id": [1, 2], "name": ["one", "two"]},
        "plain": {"id": [1], "name": ["just-one"]},
    }
    translator: Translator[str, str, int] = Translator(MemoryFetcher(data)).initialize_sources(
        settle_transformers=False
    )

    for source in translator.sources:
        if source.endswith("_bitmask"):
            translator.register_transformer(source, BitmaskTransformer())

    assert translator._tx._transformers.keys() == {"flags_bitmask"}
    assert translator.translate((3,), names="flags_bitmask") == ("1:one & 2:two",)
    assert translator.translate((1,), names="plain") == ("1:just-one",)


class TestTrimming:
    """Settling drops transformers for sources that are not served, and says which."""

    def test_unserved_source_is_dropped(self):
        translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA), transformers={"typo": Marker("x")})

        with pytest.warns(TranslationWarning, match="not served"):
            translator.initialize_sources(settle_transformers=True)

        assert "typo" not in translator.transformers

    def test_served_source_survives(self):
        translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA), transformers={"bitmasks": Marker("x")})

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            translator.initialize_sources(settle_transformers=True)

        assert translate(translator) == "1:one|x"

    def test_fetcher_serving_nothing_drops_everything(self):
        """Every registration is unreachable; the auto-installed TestFetcher exemption must not cover this."""
        translator: Translator[str, str, int] = Translator(_EmptyFetcher({}), transformers={"gone": Marker("x")})

        with pytest.warns(TranslationWarning, match="not served"):
            translator.initialize_sources(settle_transformers=True)

        assert not translator.transformers

    def test_discarded_optional_child_is_named(self):
        """A `[transform]`-section outlives a child discarded during discovery; say so instead of crying typo."""
        translator: Translator[str, str, int] = Translator(
            MultiFetcher(MemoryFetcher(DATA), _RaisingFetcher({}, optional=True)),
            transformers={"served_by_the_discarded_child": Marker("x")},
        )

        with pytest.warns(TranslationWarning, match="source discovery raised for 1 optional fetcher") as record:
            translator.initialize_sources(settle_transformers=True)

        assert "_RaisingFetcher" in str(record[0].message), "the discarded child must be identifiable"

    def test_child_without_sources_is_not_named(self):
        """It reported zero sources, so it would have served none: a registration naming one is a real typo."""
        translator: Translator[str, str, int] = Translator(
            MultiFetcher(MemoryFetcher(DATA), _EmptyFetcher({}, optional=True)),
            transformers={"typo": Marker("x")},
        )

        with pytest.warns(TranslationWarning, match="not served") as record:
            translator.initialize_sources(settle_transformers=True)

        assert "source discovery raised" not in str(record[0].message)

    def test_auto_installed_test_fetcher_keeps_everything(self):
        """It reports no sources but serves every one, so an empty list means unknown, not none."""
        with pytest.warns(TranslationWarning, match="No fetcher given"):
            translator: Translator[str, str, int] = Translator(transformers={"anything": Marker("x")})

        with warnings.catch_warnings():
            warnings.simplefilter("error", TranslationWarning)
            translator.initialize_sources(settle_transformers=True)

        assert "anything" in translator.transformers

    def test_inline_data_settles_at_construction(self):
        """Sources are fixed from birth, so there is nothing a later pass could learn."""
        with pytest.warns(TranslationWarning, match="not served"):
            translator: Translator[str, str, int] = Translator({"a": {1: "one"}}, transformers={"typo": Marker("x")})

        assert not translator.transformers

    def test_translation_map_settles_at_construction(self):
        cache = Translator[str, str, int]({"a": {1: "one"}}).cache
        with pytest.warns(TranslationWarning, match="not served"):
            translator: Translator[str, str, int] = Translator(cache, transformers={"typo": Marker("x")})

        assert not translator.transformers

    def test_registering_after_settling_raises(self):
        translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA))
        translator.initialize_sources(settle_transformers=True)

        with pytest.raises(TransformerStateError, match="settled") as exc_info:
            translator.register_transformer("bitmasks", Marker("x"))
        assert exc_info.value.__notes__ == [HINT.format(source="'bitmasks'")]

    def test_registering_on_inline_data_raises(self):
        translator: Translator[str, str, int] = Translator({"a": {1: "one"}})

        with pytest.raises(TransformerStateError, match="settled") as exc_info:
            translator.register_transformer("a", Marker("x"))
        assert exc_info.value.__notes__ == [HINT.format(source="'a'")]

    def test_reading_before_settling_raises(self):
        translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA))

        with pytest.raises(TransformerStateError, match="not settled"):
            _ = translator.transformers


class TestSettlingIsRecoverable:
    """A promoted warning must leave the misconfiguration in place, or it vanishes from the retry."""

    def test_promoted_trim_warning_reproduces(self):
        translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA), transformers={"typo": Marker("x")})

        for _ in range(3):
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                with pytest.raises(TranslationWarning, match="not served"):
                    translate(translator)
            assert not translator._tx.frozen, "a raised settle must not pass as done"
            assert "typo" in translator._tx._transformers, "nor drop what it failed to report"

    def test_wrapped_test_fetcher_drops_everything(self):
        """A MultiFetcher routes only reported sources, so a wrapped TestFetcher serves none."""
        translator: Translator[str, str, int] = Translator(
            MultiFetcher(_TestFetcher([])), transformers={"anything": Marker("x")}
        )

        with pytest.warns(TranslationWarning, match="not served"):
            translator.initialize_sources(settle_transformers=True)

        assert "anything" not in translator.transformers

    def test_subset_snapshot_does_not_warn(self):
        """`go_offline` chose the subset, so being told what it excludes is noise."""
        data = {name: {"id": [1], "name": [name]} for name in ("a", "b")}
        translator: Translator[str, str, int] = Translator(
            MemoryFetcher(data), transformers={"a": Marker("x"), "b": Marker("y")}
        )

        with warnings.catch_warnings():
            warnings.simplefilter("error", TranslationWarning)
            translator.go_offline({"a": [1]}, names="a")

        assert "b" not in translator.transformers, "still trimmed, just not announced"

    def test_subset_snapshot_leaves_views_alone(self):
        data = {name: {"id": [1], "name": [name]} for name in ("a", "b")}
        translator: Translator[str, str, int] = Translator(
            MemoryFetcher(data), transformers={"a": Marker("x"), "b": Marker("y")}
        )
        view = translator.initialize_sources(settle_transformers=True).transformers

        translator.go_offline({"a": [1]}, names="a")

        assert view.keys() == {"a", "b"}
        assert translator.transformers.keys() == {"a"}


class TestProviderRaises:
    DATA = {
        "bitmasks": {"id": [1], "name": ["one"]},
        "boom": {"id": [1], "name": ["kaboom"]},
    }

    def test_note_names_the_source_and_the_fetcher(self):
        fetcher = _RaisingProvider(self.DATA)
        translator: Translator[str, str, int] = Translator(fetcher)

        with pytest.raises(ValueError) as info:
            translator.initialize_sources()

        assert str(info.value) == "provider is down", "the original exception is annotated, never replaced"
        notes = "\n".join(info.value.__notes__)
        assert "Fetcher.get_transformer('boom')" in notes, "the query that raised must be identifiable"
        assert f"fetcher={fetcher}" in notes, "and so must the fetcher it was made against"

    def test_instance_is_untouched(self):
        fetcher = _RaisingProvider(self.DATA)
        translator: Translator[str, str, int] = Translator(fetcher)

        with pytest.raises(ValueError, match="provider is down"):
            translator.initialize_sources()

        assert translator._tx._transformers == {}, "'bitmasks' answered before 'boom' raised"

        fetcher.recovered = True
        translator.initialize_sources()
        assert translator._tx._transformers.keys() == {"bitmasks", "boom"}, "a failed pass must be retried in full"


@pytest.mark.parametrize("how", ["init", "method"])
def test_update_ids_expands_fetched_ids(how):
    """With ``return_all=False``, IDs 1 and 2 are fetched only if ``update_ids()`` runs before the fetch."""
    translator = make_translator(how, {"bitmasks": BitmaskTransformer()}, return_all=False)

    assert translator.translate((3,), names="bitmasks") == ("1:one & 2:two",)


@pytest.mark.parametrize("added", ["before", "after"])
def test_go_offline_widens_the_fetch_only_for_transformers_in_place(added):
    """Backs the transformation primer: a transformer added after ``go_offline()`` misses that fetch."""
    data = {"bitmasks": {"id": [1, 2, 3], "name": ["one", "two", "both"]}}
    fetcher = MemoryFetcher[str, int](data, return_all=False)
    transformers = {"bitmasks": BitmaskTransformer()}

    translator = Translator[str, str, int](fetcher, transformers=transformers if added == "before" else None)
    translator.go_offline({"bitmasks": [3]})
    if added == "after":
        translator = translator.copy(transformers=transformers)

    assert sorted(translator.cache.to_dicts()["bitmasks"]["id"]) == ([1, 2, 3] if added == "before" else [3])


class TestRetention:
    """The marker makes a doubled application visible: the offline path re-applies transformers to the raw translations
    extracted from the cache, so baking them into the cached values would stack them twice.
    """

    @pytest.fixture
    def translator(self) -> Translator[str, str, int]:
        return Translator(MemoryFetcher(DATA), transformers={"bitmasks": Marker("x")})

    def test_online(self, translator):
        assert translate(translator) == "1:one|x"

    def test_offline(self, translator):
        translator.go_offline()
        assert translator._tx._transformers.keys() == {"bitmasks"}
        assert translate(translator) == "1:one|x"

    def test_offline_twice(self, translator):
        translator.go_offline()
        assert translate(translator) == "1:one|x"
        assert translate(translator) == "1:one|x", "repeated translation must not stack the transformer"

    def test_copy_while_online(self, translator):
        assert translate(translator.copy()) == "1:one|x"

    def test_offline_copy_keeps_its_cache_transformed(self, translator):
        """A TranslationMap bakes transformers in at construction, so the copy's cache must be rebound to them."""
        translator.go_offline()
        copy = translator.copy()

        assert copy.cache["bitmasks"][1] == translator.cache["bitmasks"][1] == "1:one|x"

    def test_copy_while_offline(self, translator):
        translator.go_offline()
        assert translate(translator.copy()) == "1:one|x"

    def test_copy_clones_transformers(self, translator):
        copy = translator.copy()
        assert copy._tx._transformers["bitmasks"] is not translator._tx._transformers["bitmasks"]

    def test_shallow_copy_is_independent(self, translator):
        copy = shallow_copy(translator)
        copy.register_transformer("bitmasks", Marker("y"), on_existing="overwrite")

        assert translate(translator) == "1:one|x"
        assert translate(copy) == "1:one|y"

    def test_copy_override(self, translator):
        copy = translator.copy(transformers={"bitmasks": Marker("y")})
        assert translate(copy) == "1:one|y"
        assert translate(translator) == "1:one|x"

    def test_copy_rejects_fetcher_override(self, translator):
        with pytest.raises(TypeError, match="FetcherCopyMode"):
            translator.copy(fetcher=MemoryFetcher(DATA))

    @pytest.mark.parametrize("mode", ["keep", "copy", "auto"])
    def test_copy_fetcher_modes(self, translator, mode):
        copy = translator.copy(fetcher=mode)
        assert (copy.fetcher is translator.fetcher) == (mode == "keep")
        assert translate(copy) == "1:one|x"

    @pytest.mark.parametrize("mode", ["keep", "copy", "auto"])
    def test_copy_fetcher_modes_offline(self, translator, mode):
        """The mode only distinguishes clone-vs-reuse while online; offline always shares cached records."""
        translator.go_offline()
        copy = translator.copy(fetcher=mode)

        original_records = translator.cache._extract_translations()["bitmasks"]
        copy_records = copy.cache._extract_translations()["bitmasks"]
        assert copy_records is original_records

        assert translate(copy) == "1:one|x"

    def test_restore_roundtrip(self, translator, tmp_path):
        path = tmp_path / "translator.pkl"
        translator.go_offline(path=path)

        restored: Translator[str, str, int] = Translator.restore(path)
        assert restored._tx._transformers.keys() == {"bitmasks"}
        assert translate(restored) == "1:one|x"


@pytest.mark.parametrize("clone", [deepcopy, _unpickle, Translator.copy])
def test_clone_still_translates(clone):
    """A clone taken before the first query pass must still run it, and translate correctly."""
    translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA)).go_offline()  # Offline: pickle needs it.

    copied = clone(translator)
    assert translate(copied) == "1:one"


@pytest.mark.parametrize("offline", [False, True])
def test_freed_without_the_cyclic_gc(offline):
    """A dropped instance must not wait for the cyclic GC, holding on to its fetcher and the connections it owns."""
    translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA), transformers={"bitmasks": Marker("x")})
    assert translate(translator) == "1:one|x"
    if offline:
        translator.go_offline()

    ref = weakref.ref(translator)
    gc.disable()
    try:
        del translator
        assert ref() is None
    finally:
        gc.enable()


class Counting(Transformer[int]):
    """Records how many times each hook ran. Transformers are expected to be idempotent; this one is not."""

    def __init__(self) -> None:
        self.update_ids_calls = 0
        self.update_translations_calls = 0

    def update_ids(self, ids: set[int], /) -> None:  # noqa: ARG002
        self.update_ids_calls += 1

    def update_translations(self, translations: dict[int, str], /) -> None:  # noqa: ARG002
        self.update_translations_calls += 1

    def try_add_missing_key(self, key: int, /, *, translations: MutableMapping[int, str]) -> None: ...


@pytest.mark.parametrize(("max_fails", "expected"), [(1.0, 1), (0.0, 2)])
def test_update_translations_call_count_depends_on_the_caller(max_fails, expected, caplog):
    """Documents actual behavior: transformers must be idempotent.

    Verification re-applies the transformer, and it runs whenever ``max_fails < 1`` *or* ``DEBUG`` logging is on -- so
    the count is a property of the call, not of the transformer.
    """
    transformer = Counting()
    translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA), transformers={"bitmasks": transformer})

    # DEBUG triggers verification regardless of `max_fails`, and the test suite enables it globally.
    caplog.set_level(logging.INFO, logger="id_translation")
    translator.translate((1,), names="bitmasks", max_fails=max_fails)

    assert transformer.update_ids_calls == 1, "IDs are transformed once, before the fetch"
    assert transformer.update_translations_calls == expected


def test_override_is_not_called_during_construction():
    """An override may touch attributes that `__init__` has not created yet, so it must not run from there."""
    seen: list[str] = []

    class Strict(Translator[str, str, int]):
        def register_transformer(self, source, transformer, *, on_existing="raise"):
            assert self.fmt, "attributes created after the transformers argument is applied"
            seen.append(source)
            super().register_transformer(source, transformer, on_existing=on_existing)

    translator = Strict(MemoryFetcher(DATA), transformers={"bitmasks": Marker("x")})
    assert seen == [], "the constructor must use the private path"

    translator.register_transformer("bitmasks", Marker("y"), on_existing="append")
    assert seen == ["bitmasks"], "the override still applies once construction is done"
    assert translate(translator) == "1:one|x|y", "and both are registered all the same"


class TestSharedInstance:
    @staticmethod
    @pytest.fixture
    def translator_with_lock() -> tuple[Translator[str, str, int], Transformer[int]]:
        class Locked(Marker):
            def __init__(self) -> None:
                super().__init__("locked")
                self.lock = threading.Lock()  # Not deep-copyable, and only reached while copying state.

        shared = Locked()
        fetcher = MemoryFetcher[str, int](TestSharedInstance.DATA)
        return Translator[str, str, int](fetcher, transformers={"a": shared, "b": shared}), shared

    DATA = {
        "a": {"id": [1], "name": ["a1"]},
        "b": {"id": [1], "name": ["b1"]},
    }

    @pytest.fixture
    def transformer(self) -> Counting:
        return Counting()

    @pytest.fixture
    def translator(self, transformer: Counting) -> Translator[str, str, int]:
        return Translator(
            MemoryFetcher(self.DATA),
            transformers={"a": transformer, "b": transformer},
        )

    def test_same_object_for_both_sources(self, translator, transformer):
        assert translator._tx._transformers["a"] is transformer
        assert translator._tx._transformers["b"] is transformer

    def test_state_is_shared_between_sources(self, translator, transformer):
        """Documents actual behavior: a per-source instance is *not* made, so state accumulates across sources."""
        for name in ("a", "b"):
            translator.translate((1,), names=name)

        assert transformer.update_ids_calls == 2, "one call per source, on the same instance"

    def test_copy_reuses_the_original_when_it_cannot_be_cloned(self, translator_with_lock):
        """A failure partway through deepcopy must not leave a half-built shell for the next source."""
        translator, shared = translator_with_lock

        with pytest.warns(TranslationWarning, match="Failed to clone the transformer"):
            copy = translator.copy()

        assert copy._tx._transformers["a"] is shared, "both sources fall back to the original"
        assert copy._tx._transformers["b"] is shared
        assert copy.translate((1,), names="a") == ("1:a1|locked",), "the copy must still work"
        assert copy.translate((1,), names="b") == ("1:b1|locked",)

    def test_clone_failure_hint_warns_about_its_side_effect(self):
        """The hint names the escape, and following it also stops the copy asking the fetcher for more."""

        class Unclonable(Marker):
            def __deepcopy__(self, memo: dict[int, object]) -> "Unclonable":
                raise TypeError("cannot clone me")

        class Providing(MemoryFetcher[str, int]):
            def get_transformer(self, source: str) -> Transformer[int] | None:
                return Marker("provided") if source == "plain" else None

        data = {"a": {"id": [1], "name": ["a1"]}, "plain": {"id": [1], "name": ["p1"]}}

        translator = Translator[str, str, int](Providing(data), transformers={"a": Unclonable("A")})
        with pytest.warns(TranslationWarning, match="stops the copy asking the fetcher") as caught:
            plain_copy = translator.copy()
        assert "Failed to clone the transformer for 'a'" in str(caught[0].message)
        plain_copy.initialize_sources()
        assert "plain" in plain_copy._tx._transformers, "unaffected: the plain copy still queries the fetcher"

        translator = Translator[str, str, int](Providing(data), transformers={"a": Unclonable("A")})
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            hinted_copy = translator.copy(transformers={"a": Unclonable("A")})  # the hint's suggested remedy
        hinted_copy.initialize_sources()
        assert "plain" not in hinted_copy._tx._transformers, "the hint documents this trade-off, but still makes it"

    def test_copy_isolates_a_failed_clone(self):
        """Two transformers sharing an un-copyable helper: neither copy may see a half-built one.

        ``deepcopy`` registers an object before copying its state, so a memo carried across transformers must drop a
        failed attempt's entries. Otherwise the second one gets the shell left behind by the first, with no warning.
        """

        class Vocabulary:
            def __init__(self) -> None:
                self.suffix = "!"
                self.lock = threading.Lock()  # Copied after `suffix`, and not deep-copyable.

        class Tagged(Transformer[int]):
            def __init__(self, vocabulary: Vocabulary, tag: str) -> None:
                self.vocabulary = vocabulary
                self.tag = tag

            def update_ids(self, ids: set[int], /) -> None: ...

            def update_translations(self, translations: dict[int, str], /) -> None:
                for key in translations:
                    translations[key] += f"|{self.tag}{self.vocabulary.suffix}"

            def try_add_missing_key(self, key: int, /, *, translations: MutableMapping[int, str]) -> None: ...

        shared = Vocabulary()
        translator: Translator[str, str, int] = Translator(
            MemoryFetcher(self.DATA),
            transformers={"a": Tagged(shared, "A"), "b": Tagged(shared, "B")},
        )

        with pytest.warns(TranslationWarning, match="Failed to clone the transformer") as caught:
            copy = translator.copy()

        assert len(caught) == 2, "each source must be reported"
        assert copy.translate((1,), names="a") == ("1:a1|A!",)
        assert copy.translate((1,), names="b") == ("1:b1|B!",), "must not get a half-built helper"

    def test_copy_keeps_sharing_after_an_unrelated_failure(self):
        class Holder:
            pass

        class Tagged(Marker):
            def __init__(self, tag: str, holder: Holder) -> None:
                super().__init__(tag)
                self.holder = holder

        class Locked(Marker):
            def __init__(self) -> None:
                super().__init__("locked")
                self.lock = threading.Lock()  # Not deep-copyable.

        holder = Holder()
        data = {**self.DATA, "c": {"id": [1], "name": ["c1"]}}
        entries = {"c": Locked(), "a": Tagged("A", holder), "b": Tagged("B", holder)}
        translator = Translator[str, str, int](MemoryFetcher(data), transformers=entries)

        with pytest.warns(TranslationWarning, match="Failed to clone the transformer for 'c'"):
            copy = translator.copy()

        a, b = copy._tx._transformers["a"], copy._tx._transformers["b"]
        assert isinstance(a, Tagged) and isinstance(b, Tagged)
        assert a.holder is b.holder, "shared before the copy, so shared after it"
        assert a.holder is not holder

    @pytest.mark.parametrize("failure_first", [True, False])
    def test_copy_never_splices_a_failed_clone_into_a_composite(self, failure_first):
        """A composite embedding an un-copyable member must fall back (and warn) -- in either registration order.

        Mapping the failed clone to itself in a shared deepcopy memo would make the composite's copy 'succeed'
        with the original spliced in, silently sharing state between the instances -- but only for the order
        where the bare entry was cloned first.
        """

        class Composite(Marker):
            def __init__(self, inner: Transformer[int]) -> None:
                super().__init__("composite")
                self.inner = inner

        class Locked(Marker):
            def __init__(self) -> None:
                super().__init__("locked")
                self.lock = threading.Lock()  # Not deep-copyable.

        shared = Locked()
        entries = {"a": shared, "b": Composite(shared)}
        if not failure_first:
            entries = {"b": entries["b"], "a": entries["a"]}
        translator = Translator[str, str, int](MemoryFetcher(self.DATA), transformers=entries)

        with pytest.warns(TranslationWarning, match="Failed to clone the transformer") as caught:
            copy = translator.copy()

        assert len(caught) == 2, "each source must be reported"
        assert copy._tx._transformers["a"] is shared
        assert copy._tx._transformers["b"] is translator._tx._transformers["b"], "reused wholesale, never half-spliced"

    def test_copy_preserves_sharing_with_a_stack(self):
        shared, other = Marker("S"), Marker("O")
        fetcher = MemoryFetcher[str, int](self.DATA)
        translator = Translator[str, str, int](fetcher, transformers={"a": shared, "b": [shared, other]})

        copy = translator.copy()
        stack = copy._tx._transformers["b"]
        assert isinstance(stack, TransformerStack)

        assert copy._tx._transformers["a"] is stack.transformers[0], "the sharing must survive the copy"
        assert copy._tx._transformers["a"] is not shared, "but it is a copy"

    def test_copy_preserves_the_sharing(self, translator):
        copy = translator.copy()

        assert copy._tx._transformers["a"] is copy._tx._transformers["b"]
        assert copy._tx._transformers["a"] is not translator._tx._transformers["a"], "but it is a copy"

    def test_copy_preserves_sharing_through_any_composite(self):
        class Composite(Transformer[int]):
            """A user-defined chain; the ``Translator`` knows nothing about its internals."""

            def __init__(self, inner: Transformer[int]) -> None:
                self.inner = inner

            def update_ids(self, ids: set[int], /) -> None:
                self.inner.update_ids(ids)

            def update_translations(self, translations: dict[int, str], /) -> None:
                self.inner.update_translations(translations)

            def try_add_missing_key(self, key: int, /, *, translations: MutableMapping[int, str]) -> None: ...

        shared = Marker("S")
        translator: Translator[str, str, int] = Translator(
            MemoryFetcher(self.DATA),
            transformers={"a": Composite(shared), "b": shared},
        )

        copy = translator.copy()
        composite = copy._tx._transformers["a"]
        assert isinstance(composite, Composite)

        assert composite.inner is copy._tx._transformers["b"], "the sharing must survive the copy"
        assert copy._tx._transformers["b"] is not shared, "but it is a copy"
