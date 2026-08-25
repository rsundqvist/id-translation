"""Tests for transformers owned by the ``Translator``; see ``Translator.register_transformer``."""

import logging
import pickle
import threading
import warnings
from collections.abc import MutableMapping
from copy import deepcopy

import pytest

from id_translation import Translator
from id_translation.exceptions import TransformerConflictError
from id_translation.fetching import MemoryFetcher, MultiFetcher
from id_translation.transform import BitmaskTransformer, TransformerStack
from id_translation.transform.types import Transformer

from .conftest import DATA, Marker, make_translator, translate


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


def test_default_is_empty():
    assert Translator[str, str, int](MemoryFetcher(DATA)).transformers == {}


@pytest.mark.parametrize("how", ["init", "method"])
def test_registration(how):
    """Both registration paths must produce the same result."""
    transformer = Marker("x")
    translator = make_translator(how, {"bitmasks": transformer})

    assert translator.transformers == {"bitmasks": transformer}
    assert translator.transformers["bitmasks"] is transformer
    assert translate(translator) == "1:one|x"


class TestLiveDict:
    """``transformers`` hands out the live dict until 2.0.0 makes it read-only."""

    @pytest.fixture
    def translator(self) -> Translator[str, str, int]:
        return Translator(MemoryFetcher(DATA), transformers={"bitmasks": Marker("x")})

    def test_is_live(self, translator):
        view = translator.transformers
        translator.register_transformer("other", Marker("y"))
        assert view.keys() == {"bitmasks", "other"}, "should reflect later registrations"

    def test_mutation_is_visible(self, translator):
        """Documents actual behavior; register_transformer() is the supported path."""
        translator.transformers["other"] = Marker("y")
        assert translator.transformers.keys() == {"bitmasks", "other"}


class TestSequenceNormalization:
    @pytest.mark.parametrize("how", ["init", "method"])
    def test_chain_becomes_a_stack(self, how):
        first, second = Marker("first"), Marker("second")
        translator = make_translator(how, {"bitmasks": [first, second]})

        stack = translator.transformers["bitmasks"]
        assert isinstance(stack, TransformerStack)
        assert stack.transformers == (first, second), "members must keep the given order"
        assert translate(translator) == "1:one|first|second"

    def test_single_element_unwraps(self):
        transformer = Marker("x")
        translator = make_translator("method", {"bitmasks": [transformer]})

        assert translator.transformers["bitmasks"] is transformer

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
        """A Transformer implementation may itself be a Sequence."""

        class SequenceMarker(tuple[int, ...], Transformer[int]):
            __slots__ = ()

            def update_ids(self, ids: set[int], /) -> None: ...

            def update_translations(self, translations: dict[int, str], /) -> None:
                for key in translations:
                    translations[key] += "|seq"

            def try_add_missing_key(self, key: int, /, *, translations: MutableMapping[int, str]) -> None: ...

        transformer = SequenceMarker([1, 2, 3])
        translator = make_translator("method", {"bitmasks": transformer})

        assert translator.transformers["bitmasks"] is transformer
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

        assert not translator.transformers["bitmasks"], "precondition: the transformer is falsy"
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
        old = translator.transformers["bitmasks"]
        with pytest.raises(ValueError, match="already registered"):
            translator.register_transformer("bitmasks", Marker("new"))
        assert translator.transformers["bitmasks"] is old

    def test_append(self, translator):
        old = translator.transformers["bitmasks"]
        new = Marker("new")
        translator.register_transformer("bitmasks", new, on_existing="append")

        stack = translator.transformers["bitmasks"]
        assert isinstance(stack, TransformerStack)
        assert stack.transformers == (old, new), "the existing transformer runs first"
        assert translate(translator) == "1:one|old|new"

    def test_append_flattens(self, translator):
        """Appending a chain to a stack must not nest."""
        old = translator.transformers["bitmasks"]
        first, second = Marker("first"), Marker("second")
        translator.register_transformer("bitmasks", [first, second], on_existing="append")

        stack = translator.transformers["bitmasks"]
        assert isinstance(stack, TransformerStack)
        assert stack.transformers == (old, first, second)

    def test_append_to_unregistered_source(self, translator):
        transformer = Marker("x")
        translator.register_transformer("other", transformer, on_existing="append")
        assert translator.transformers["other"] is transformer

    def test_overwrite(self, translator):
        new = Marker("new")
        translator.register_transformer("bitmasks", new, on_existing="overwrite")

        assert translator.transformers["bitmasks"] is new
        assert translate(translator) == "1:one|new"

    def test_bad_value_raises(self, translator):
        with pytest.raises(TypeError, match="on_existing"):
            translator.register_transformer("bitmasks", Marker("new"), on_existing="APPEND")


def test_register_from_discovered_sources():
    """The headline use case: sources are known only after ``initialize_sources()``."""
    data = {
        "flags_bitmask": {"id": [1, 2], "name": ["one", "two"]},
        "plain": {"id": [1], "name": ["just-one"]},
    }
    translator: Translator[str, str, int] = Translator(MemoryFetcher(data)).initialize_sources()

    for source in translator.sources:
        if source.endswith("_bitmask"):
            translator.register_transformer(source, BitmaskTransformer())

    assert translator.transformers.keys() == {"flags_bitmask"}
    assert translator.translate((3,), names="flags_bitmask") == ("1:one & 2:two",)
    assert translator.translate((1,), names="plain") == ("1:just-one",)


class TestUnknownSources:
    def test_warns(self):
        translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA))
        translator.register_transformer("typo", Marker("x"))

        with pytest.warns(UserWarning, match="unknown sources"):
            translator.initialize_sources()

    def test_known_source_does_not_warn(self):
        translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA), transformers={"bitmasks": Marker("x")})

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            translator.initialize_sources()

    def test_warns_once(self):
        """The check runs per translate; in a request loop, warning each time is noise."""
        translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA), transformers={"typo": Marker("x")})

        with pytest.warns(UserWarning, match="unknown sources"):
            translate(translator)

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            translate(translator)
            translate(translator)

    def test_new_registration_is_checked(self):
        """Warning once must not mean checking once: a later registration may name a source of its own."""
        translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA), transformers={"typo": Marker("x")})
        with pytest.warns(UserWarning, match="unknown sources"):
            translate(translator)

        translator.register_transformer("another-typo", Marker("y"))

        with pytest.warns(UserWarning, match="another-typo"):
            translate(translator)

    def test_fetcher_serving_nothing_still_warns(self):
        """Every registration is unreachable -- the case the auto-installed TestFetcher exemption must not cover."""
        translator: Translator[str, str, int] = Translator(_EmptyFetcher({}), transformers={"gone": Marker("x")})

        with pytest.warns(UserWarning, match="unknown sources"):
            translator.initialize_sources()

    def test_discarded_optional_child_is_named(self):
        """A `[transform]`-section outlives a child discarded during discovery; say so instead of crying typo."""
        translator: Translator[str, str, int] = Translator(
            MultiFetcher(MemoryFetcher(DATA), _RaisingFetcher({}, optional=True)),
            transformers={"served_by_the_discarded_child": Marker("x")},
        )

        with pytest.warns(UserWarning, match="source discovery raised for 1 optional fetcher") as record:
            translator.initialize_sources()

        assert "_RaisingFetcher" in str(record[0].message), "the discarded child must be identifiable"

    def test_child_without_sources_is_not_named(self):
        """It reported zero sources, so it would have served none -- a registration naming one is a real typo."""
        translator: Translator[str, str, int] = Translator(
            MultiFetcher(MemoryFetcher(DATA), _EmptyFetcher({}, optional=True)),
            transformers={"typo": Marker("x")},
        )

        with pytest.warns(UserWarning, match="unknown sources") as record:
            translator.initialize_sources()

        assert "source discovery raised" not in str(record[0].message)

    def test_failed_discovery_does_not_disable_the_check(self):
        """The flag must be set after the sources are read, or one transient failure silences every later check."""
        fetcher = _RaisingFetcher(DATA, optional=False)
        translator: Translator[str, str, int] = Translator(fetcher, transformers={"typo": Marker("x")})

        with pytest.raises(ValueError, match="no connection"):
            translator.initialize_sources()

        fetcher.recovered = True
        with pytest.warns(UserWarning, match="unknown sources"):
            translator.initialize_sources()

    def test_promoted_warning_does_not_disable_the_check(self):
        """Under `-W error` the warning raises; the misconfiguration must reproduce instead of vanishing on retry."""
        translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA), transformers={"typo": Marker("x")})

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            for _ in range(3):
                with pytest.raises(UserWarning, match="unknown sources"):
                    translate(translator)

    def test_auto_installed_test_fetcher_is_exempt(self):
        """It reports no sources but serves every source, so nothing registered is unreachable."""
        with pytest.warns(UserWarning, match="No fetcher given"):
            translator: Translator[str, str, int] = Translator(transformers={"anything": Marker("x")})

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            translator.initialize_sources()

    def test_no_fetcher_does_not_warn(self):
        """`Translator()` installs a TestFetcher, which reports no sources but serves every source."""
        translator: Translator[str, str, int] = Translator()
        translator.register_transformer("bitmasks", Marker("x"))

        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            translator.initialize_sources()

    def test_offline_registration_warns_immediately(self):
        """Offline sources are fixed and known, e.g. after ``restore()``; a typo would otherwise never surface."""
        translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA)).go_offline()

        with pytest.warns(UserWarning, match="unknown sources"):
            translator.register_transformer("typo", Marker("x"))

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            translator.initialize_sources()  # Still a silent no-op offline; the registration already warned.

    def test_offline_registration_for_known_source_does_not_warn(self):
        translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA)).go_offline()

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            translator.register_transformer("bitmasks", Marker("x"))

    def test_promoted_offline_warning_rolls_back_the_registration(self):
        """Under `-W error` the caller sees a raise, so the registration must not stick behind it."""
        translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA)).go_offline()

        for _ in range(2):  # A retry must report the same problem, not a conflict with the failed attempt.
            with warnings.catch_warnings(), pytest.raises(UserWarning, match="unknown sources"):
                warnings.simplefilter("error")
                translator.register_transformer("typo", Marker("x"))

        assert "typo" not in translator.transformers

    @pytest.mark.parametrize("on_existing", ["append", "overwrite"])
    def test_promoted_offline_warning_restores_the_previous_registration(self, on_existing):
        """Rolling back means undoing the call, not just dropping what it added: `source` may already have had one."""
        data = {name: {"id": [1], "name": [name]} for name in ("a", "b")}
        translator: Translator[str, str, int] = Translator(
            MemoryFetcher(data), transformers={"a": Marker("x"), "b": Marker("y")}
        )
        translator.go_offline({"a": [1]}, names="a")  # The cache can serve only 'a', so 'b' is now unknown.
        old = translator.transformers["b"]

        with warnings.catch_warnings(), pytest.raises(UserWarning, match="unknown sources"):
            warnings.simplefilter("error")
            translator.register_transformer("b", Marker("z"), on_existing=on_existing)

        assert translator.transformers["b"] is old, "neither replaced nor chained onto"

        # As if the failed call never happened: the conflict is with the original, not with what it tried to register.
        with pytest.raises(TransformerConflictError, match=r"Marker\('y'\) is already registered"):
            translator.register_transformer("b", Marker("z"))

    def test_rolled_back_registration_is_not_left_queued(self):
        """The rewind must cover the queue too, or the next check reports a registration that was undone."""
        data = {name: {"id": [1], "name": [name]} for name in ("a", "b")}
        translator: Translator[str, str, int] = Translator(
            MemoryFetcher(data), transformers={"a": Marker("x"), "b": Marker("y")}
        )
        translator.go_offline({"a": [1]}, names="a")  # The cache can serve only 'a', so 'b' is now unknown.

        with warnings.catch_warnings(), pytest.raises(UserWarning, match="unknown sources"):
            warnings.simplefilter("error")
            translator.register_transformer("b", Marker("z"), on_existing="append")

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            translator.register_transformer("a", Marker("late"), on_existing="append")  # 'a' is known: must not warn.

        assert translator.translate((1,), names="a") == ("1:a|x|late",), "and the instance still works"

    def test_inline_data_registration_warns(self):
        """Offline from birth: `initialize_sources` is a no-op, so the constructor is the only chance to warn."""
        with pytest.warns(UserWarning, match="unknown sources"):
            Translator[str, str, int]({"bitmasks": {1: "one"}}, transformers={"typo": Marker("x")})

    def test_inline_data_registration_for_known_source_does_not_warn(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            Translator[str, str, int]({"bitmasks": {1: "one"}}, transformers={"bitmasks": Marker("x")})

    def test_subset_snapshot_copy_does_not_warn(self):
        """Only explicit registration is checked; a snapshot that simply excludes a source is not a typo."""
        data = {name: {"id": [1], "name": [name]} for name in ("a", "b")}
        translator: Translator[str, str, int] = Translator(
            MemoryFetcher(data), transformers={"a": Marker("x"), "b": Marker("y")}
        )
        translator.go_offline({"a": [1]}, names="a")  # The cache can now serve only 'a'.

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            translator.copy()

    def test_snapshot_exemption_survives_a_later_registration(self):
        """The exemption is permanent; a later registration re-runs the check, which must not revisit it."""
        data = {name: {"id": [1], "name": [name]} for name in ("a", "b")}
        translator: Translator[str, str, int] = Translator(
            MemoryFetcher(data), transformers={"a": Marker("x"), "b": Marker("y")}
        )
        translator.go_offline({"a": [1]}, names="a")  # The cache can now serve only 'a'.
        copy = translator.copy()

        with pytest.warns(UserWarning, match="unknown sources") as record:
            copy.register_transformer("typo", Marker("z"))

        assert "'typo'" in str(record[0].message), "the new registration is still checked"
        assert "'b'" not in str(record[0].message), "the exempt snapshot registration must stay exempt"

    def test_go_offline_grants_the_same_exemption_as_a_copy(self):
        """`go_offline()` turns the instance itself into a snapshot; it must not warn where its own copy wouldn't."""
        data = {name: {"id": [1], "name": [name]} for name in ("a", "b")}
        translator: Translator[str, str, int] = Translator(
            MemoryFetcher(data), transformers={"a": Marker("x"), "b": Marker("y")}
        )
        translator.go_offline({"a": [1]}, names="a")  # The cache can now serve only 'a'.

        with pytest.warns(UserWarning, match="unknown sources") as record:
            translator.register_transformer("typo", Marker("z"))

        assert "'typo'" in str(record[0].message), "the new registration is still checked"
        assert "'b'" not in str(record[0].message), "'b' predates going offline, exactly like the copy's case"

    def test_old_subset_snapshot_is_exempt(self):
        """Snapshots predating the exemption were written the same way; `__setstate__` must grant it retroactively."""
        data = {name: {"id": [1], "name": [name]} for name in ("a", "b")}
        translator: Translator[str, str, int] = Translator(
            MemoryFetcher(data), transformers={"a": Marker("x"), "b": Marker("y")}
        )
        translator.go_offline({"a": [1]}, names="a")  # The cache can now serve only 'a'.

        state = translator.__getstate__()
        del state["_unverified_sources"]  # The state an older snapshot unpickles into.
        revived: Translator[str, str, int] = Translator.__new__(Translator)
        revived.__setstate__(state)

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            revived.register_transformer("a", Marker("z"), on_existing="append")


class TestProviderRaises:
    """``Fetcher.get_transformer`` is user code; a raise from it propagates, annotated with where it came from."""

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
        """The pass applies nothing, so a source answered before the failing one leaves no registration behind."""
        fetcher = _RaisingProvider(self.DATA)
        translator: Translator[str, str, int] = Translator(fetcher)

        with pytest.raises(ValueError, match="provider is down"):
            translator.initialize_sources()

        assert translator.transformers == {}, "'bitmasks' answered before 'boom' raised"

        fetcher.recovered = True
        translator.initialize_sources()
        assert translator.transformers.keys() == {"bitmasks", "boom"}, "a failed pass must be retried in full"


@pytest.mark.parametrize("how", ["init", "method"])
def test_update_ids_expands_fetched_ids(how):
    """With ``return_all=False``, IDs 1 and 2 are fetched only if ``update_ids()`` runs before the fetch."""
    translator = make_translator(how, {"bitmasks": BitmaskTransformer()}, return_all=False)

    assert translator.translate((3,), names="bitmasks") == ("1:one & 2:two",)


class TestRetention:
    """Transformers must survive ``go_offline()``/``copy()``/``restore()`` and be applied exactly once.

    The marker makes a doubled application visible: the offline path re-applies transformers to the raw translations
    extracted from the cache, so baking them into the cached values would stack them twice.
    """

    @pytest.fixture
    def translator(self) -> Translator[str, str, int]:
        return Translator(MemoryFetcher(DATA), transformers={"bitmasks": Marker("x")})

    def test_online(self, translator):
        assert translate(translator) == "1:one|x"

    def test_offline(self, translator):
        translator.go_offline()
        assert translator.transformers.keys() == {"bitmasks"}
        assert translate(translator) == "1:one|x"

    def test_offline_twice(self, translator):
        translator.go_offline()
        assert translate(translator) == "1:one|x"
        assert translate(translator) == "1:one|x", "repeated translation must not stack the transformer"

    def test_copy_while_online(self, translator):
        assert translate(translator.copy()) == "1:one|x"

    def test_copy_while_offline(self, translator):
        translator.go_offline()
        assert translate(translator.copy()) == "1:one|x"

    def test_copy_clones_transformers(self, translator):
        """User types are deep-copied, so the copy must not share transformer state with the original."""
        copy = translator.copy()
        assert copy.transformers["bitmasks"] is not translator.transformers["bitmasks"]

    def test_copy_override(self, translator):
        copy = translator.copy(transformers={"bitmasks": Marker("y")})
        assert translate(copy) == "1:one|y"
        assert translate(translator) == "1:one|x"

    def test_copy_with_new_fetcher(self, translator):
        with pytest.warns(FutureWarning, match="replaces the data source"):
            copy = translator.copy(fetcher=MemoryFetcher(DATA))
        assert translate(copy) == "1:one|x"

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
        assert restored.transformers.keys() == {"bitmasks"}
        assert translate(restored) == "1:one|x"

    def test_offline_registration_reaches_the_cache(self):
        """`translate()` rebuilds from the live registrations; `Translator.cache` must agree with it."""
        translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA)).go_offline()
        translator.register_transformer("bitmasks", Marker("late"))

        assert translate(translator) == "1:one|late"
        assert translator.cache["bitmasks"][1] == "1:one|late", "both documented access paths must transform"


@pytest.mark.parametrize("clone", [deepcopy, _unpickle, Translator.copy])
def test_clone_still_translates(clone):
    """A clone taken before the first query pass must still run it, and translate correctly."""
    translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA)).go_offline()  # Offline: pickle needs it.

    copied = clone(translator)
    assert translate(copied) == "1:one"


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
        def register_transformer(self, source, transformer, on_existing="raise"):
            assert self.fmt, "attributes created after the transformers argument is applied"
            seen.append(source)
            super().register_transformer(source, transformer, on_existing=on_existing)

    translator = Strict(MemoryFetcher(DATA), transformers={"bitmasks": Marker("x")})
    assert seen == [], "the constructor must use the private path"
    assert translate(translator) == "1:one|x", "but the transformer is registered all the same"

    translator.register_transformer("other", Marker("y"))
    assert seen == ["other"], "the override still applies once construction is done"


class TestSharedInstance:
    """One instance registered for two sources stays one object; nothing isolates per-source state."""

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
        return Translator(MemoryFetcher(self.DATA), transformers={"a": transformer, "b": transformer})

    def test_same_object_for_both_sources(self, translator, transformer):
        assert translator.transformers["a"] is transformer
        assert translator.transformers["b"] is transformer

    def test_state_is_shared_between_sources(self, translator, transformer):
        """Documents actual behavior: a per-source instance is *not* made, so state accumulates across sources."""
        for name in ("a", "b"):
            translator.translate((1,), names=name)

        assert transformer.update_ids_calls == 2, "one call per source, on the same instance"

    def test_copy_reuses_the_original_when_it_cannot_be_cloned(self, translator_with_lock):
        """A failure partway through deepcopy must not leave a half-built shell for the next source."""
        translator, shared = translator_with_lock

        with pytest.warns(UserWarning, match="Failed to clone the transformer"):
            copy = translator.copy()

        assert copy.transformers["a"] is shared, "both sources fall back to the original"
        assert copy.transformers["b"] is shared
        assert copy.translate((1,), names="a") == ("1:a1|locked",), "the copy must still work"
        assert copy.translate((1,), names="b") == ("1:b1|locked",)

    def test_clone_failure_hint_warns_about_its_side_effect(self):
        """Following the hint literally also disables fetcher-provided discovery, not just this one warning."""

        class Unclonable(Marker):
            def __deepcopy__(self, memo: dict[int, object]) -> "Unclonable":
                raise TypeError("cannot clone me")

        class Providing(MemoryFetcher[str, int]):
            def get_transformer(self, source: str) -> Transformer[int] | None:
                return Marker("provided") if source == "plain" else None

        data = {"a": {"id": [1], "name": ["a1"]}, "plain": {"id": [1], "name": ["p1"]}}

        translator = Translator[str, str, int](Providing(data), transformers={"a": Unclonable("A")})
        with pytest.warns(UserWarning, match="also disables fetcher-provided discovery") as caught:
            plain_copy = translator.copy()
        assert "Failed to clone the transformer for 'a'" in str(caught[0].message)
        plain_copy.initialize_sources()
        assert "plain" in plain_copy.transformers, "unaffected: the plain copy still queries the fetcher"

        translator = Translator[str, str, int](Providing(data), transformers={"a": Unclonable("A")})
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            hinted_copy = translator.copy(transformers=translator.transformers)  # the hint's suggested remedy
        hinted_copy.initialize_sources()
        assert "plain" not in hinted_copy.transformers, "the hint documents this trade-off, but still makes it"

    def test_copy_isolates_a_failed_clone(self):
        """Two transformers sharing an un-copyable helper: neither copy may see a half-built one.

        ``deepcopy`` registers an object before copying its state, so a memo carried across transformers would hand
        the second one the shell left behind by the first -- silently, and with no second warning.
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

        with pytest.warns(UserWarning, match="Failed to clone the transformer") as caught:
            copy = translator.copy()

        assert len(caught) == 2, "each source must be reported"
        assert copy.translate((1,), names="a") == ("1:a1|A!",)
        assert copy.translate((1,), names="b") == ("1:b1|B!",), "must not get a half-built helper"

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

        with pytest.warns(UserWarning, match="Failed to clone the transformer") as caught:
            copy = translator.copy()

        assert len(caught) == 2, "each source must be reported"
        assert copy.transformers["a"] is shared
        assert copy.transformers["b"] is translator.transformers["b"], "reused wholesale, never half-spliced"

    def test_copy_preserves_sharing_with_a_stack(self):
        """An instance registered bare under one source and inside a chain under another stays one object."""
        shared, other = Marker("S"), Marker("O")
        fetcher = MemoryFetcher[str, int](self.DATA)
        translator = Translator[str, str, int](fetcher, transformers={"a": shared, "b": [shared, other]})

        copy = translator.copy()
        stack = copy.transformers["b"]
        assert isinstance(stack, TransformerStack)

        assert copy.transformers["a"] is stack.transformers[0], "the sharing must survive the copy"
        assert copy.transformers["a"] is not shared, "but it is a copy"

    def test_copy_preserves_the_sharing(self, translator):
        """``copy()`` clones through a shared memo, so a deliberately shared instance stays shared."""
        copy = translator.copy()

        assert copy.transformers["a"] is copy.transformers["b"]
        assert copy.transformers["a"] is not translator.transformers["a"], "but it is a copy"

    def test_copy_preserves_sharing_through_any_composite(self):
        """Sharing is preserved by the memo, so it is not limited to bare entries and ``TransformerStack`` members."""

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
        composite = copy.transformers["a"]
        assert isinstance(composite, Composite)

        assert composite.inner is copy.transformers["b"], "the sharing must survive the copy"
        assert copy.transformers["b"] is not shared, "but it is a copy"
