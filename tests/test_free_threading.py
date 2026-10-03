"""Race-condition tests for free-threaded (GIL-less) Python 3.14+.

These tests run many threads against a *shared* :class:`~id_translation.Translator`
on a no-GIL (``Py_GIL_DISABLED``) interpreter. With the GIL removed, latent data
races in shared mutable state actually manifest, so we assert per-call output
correctness: any corruption from a race makes a thread's result diverge from the
single-threaded baseline and fails the test.

The whole module is skipped unless run on a free-threaded build of Python 3.14+;
individual tests additionally skip if the GIL was re-enabled at runtime (e.g. by
a C extension that is not free-threading compatible), since that would serialize
execution and give false confidence.
"""

import copy
import os
import sys
import sysconfig
import threading
from collections.abc import Callable
from typing import Any

import pandas as pd
import pytest

from id_translation import Translator
from id_translation.dio import _resolve, is_registered, resolve_io
from id_translation.dio.default import ScalarIO
from id_translation.mapping import Mapper

from .conftest import HexFetcher

_BUILD_IS_FREE_THREADED = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))

pytestmark = pytest.mark.skipif(
    not (sys.version_info >= (3, 14) and _BUILD_IS_FREE_THREADED),
    reason="Requires a free-threaded (Py_GIL_DISABLED) build of Python 3.14+.",
)

N_THREADS = min(32, (os.cpu_count() or 1) * 4)
ITERATIONS = 50

# Inputs that exercise both sources of the HexFetcher (IDs must stay within -10..9).
DICT_INPUT: dict[str, list[int]] = {
    "positive_numbers": [0, 1, 2, 3, 9],
    "negative_numbers": [-1, -5, -10],
}


def _new_translator() -> Translator[str, str, int]:
    """A fresh, self-contained online ``Translator`` (does not touch session fixtures)."""
    mapper: Mapper[str, str, None] = Mapper("equality", overrides={"p": "positive_numbers", "n": "negative_numbers"})
    return Translator(HexFetcher(), mapper=mapper, fmt="{id}:{hex}[, positive={positive}]")


@pytest.fixture(autouse=True)
def _require_gil_disabled() -> None:
    """Skip (per test) if the GIL is enabled at runtime, even on a free-threaded build."""
    if sys.version_info >= (3, 13) and sys._is_gil_enabled():
        pytest.skip("GIL re-enabled at runtime (incompatible C extension?); execution would be serialized.")


@pytest.fixture
def online_translator() -> Translator[str, str, int]:
    """A fresh online ``Translator`` backed by a ``HexFetcher``."""
    return _new_translator()


@pytest.fixture
def offline_translator() -> Translator[str, str, int]:
    """A fresh ``Translator`` with translations cached in memory (disconnected)."""
    return _new_translator().go_offline()


def _run_in_threads(
    worker: Callable[[int, int], None], *, n_threads: int = N_THREADS, iterations: int = ITERATIONS
) -> None:
    """Run ``worker(thread_index, iteration)`` in ``n_threads`` threads, started simultaneously.

    A :class:`threading.Barrier` releases every thread at once to maximize contention. Exceptions
    raised by workers (a bare ``Thread`` swallows them, which would let the test pass spuriously) are
    collected and re-raised together as a :class:`BaseExceptionGroup` in the main thread.
    """
    barrier = threading.Barrier(n_threads)
    errors: list[BaseException] = []

    def run(idx: int) -> None:
        try:
            barrier.wait(timeout=30)
        except BaseException as e:
            errors.append(e)
            barrier.abort()  # don't let other threads deadlock waiting on us
            return
        try:
            for i in range(iterations):
                worker(idx, i)
        except BaseException as e:
            errors.append(e)  # Past the barrier: aborting now would only mask this with BrokenBarrierError.

    threads = [threading.Thread(target=run, args=(i,), name=f"ft-worker-{i}") for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if errors:
        raise BaseExceptionGroup("worker(s) raised in _run_in_threads", errors)


def test_shared_translator_dict_concurrent(offline_translator: Translator[str, str, int]) -> None:
    """Pure-Python read path: shared offline Translator, ``copy=True`` dict translation.

    This is the primary signal - it avoids pandas/numpy so the GIL cannot be re-enabled by an
    extension. Any race on shared state (e.g. the ``TranslationMap`` or ``_translated_names``)
    that corrupts an individual call's result is caught by the per-call assertion.
    """
    expected = offline_translator.translate(copy.deepcopy(DICT_INPUT), copy=True)

    def worker(_idx: int, _i: int) -> None:
        result = offline_translator.translate(copy.deepcopy(DICT_INPUT), copy=True)
        assert result == expected

    _run_in_threads(worker)


def test_shared_translator_pandas_inplace(offline_translator: Translator[str, str, int]) -> None:
    """In-place pandas path: shared Translator, each thread owns its own frame, ``copy=False``.

    Each thread mutates only its private DataFrame, so a divergence points at a race in the
    Translator's *internal* shared state rather than at the (expectedly unsafe) sharing of a
    mutable target.
    """
    base = pd.DataFrame(
        {
            "positive_numbers": DICT_INPUT["positive_numbers"],
            "negative_numbers": [-1, -5, -10, -2, -3],
        }
    )
    expected = offline_translator.translate(base.copy(), copy=True)

    def worker(_idx: int, _i: int) -> None:
        df = base.copy()
        returned = offline_translator.translate(df, copy=False)
        assert returned is None
        pd.testing.assert_frame_equal(df, expected)

    _run_in_threads(worker)


def test_concurrent_io_resolution(
    offline_translator: Translator[str, str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Race the lazy DIO singleton: discard the registry, then resolve IO from many threads.

    Concurrent first-time resolutions race the singleton's creation. We assert every translation
    still produces the correct frame.
    """
    base = pd.DataFrame({"positive_numbers": DICT_INPUT["positive_numbers"]})
    expected = offline_translator.translate(base.copy(), copy=True)

    monkeypatch.setattr(_resolve, "_INSTANCE", None)  # Workers race to create the registry.

    def worker(_idx: int, _i: int) -> None:
        out = offline_translator.translate(base.copy(), copy=True)
        pd.testing.assert_frame_equal(out, expected)

    _run_in_threads(worker)


@pytest.mark.gating
def test_concurrent_register_unregister(monkeypatch: pytest.MonkeyPatch) -> None:
    """Race ``register()``/``unregister()`` against ``resolve_io()`` and against each other.

    Writers toggle a hand-registered and an opt-in implementation, neither of which handles ``int``.
    Readers must always resolve ``int`` to ``ScalarIO`` and never see an implementation twice.
    """

    class HandRegistered(ScalarIO[int, str, str]):
        priority = 1500  # Ties with ScalarIO, so registering it shifts ScalarIO's rank.

        @classmethod
        def handles_type(cls, arg: Any) -> bool:  # noqa: ARG003
            return False

    class OptInOnly(HandRegistered):
        priority = -1500

    monkeypatch.setattr(_resolve, "_INSTANCE", None)
    repository = _resolve._get_repository()
    OptInOnly.register()  # Discovered or not, all that matters is that the state keeps changing.

    def worker(idx: int, _i: int) -> None:
        match idx % 4:
            case 0:
                HandRegistered.register()
                HandRegistered.unregister()
            case 1:
                OptInOnly.unregister()
                OptInOnly.register()
            case _:
                assert type(resolve_io(1)) is ScalarIO
                all_ios = repository.all_ios
                assert len(all_ios) == len(set(all_ios))

    _run_in_threads(worker, iterations=500)


@pytest.mark.gating
def test_concurrent_registration_loses_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent ``register()`` calls must all take effect; ``dio`` promises they are safe at any time.

    Each thread registers its own implementations, so any that end up unregistered were lost to a racing writer. The
    copy-on-write state keeps readers safe on its own; this is what the writers' lock is for.
    """
    per_thread = 20

    def make(name: str) -> type[ScalarIO[int, str, str]]:
        attrs = {"priority": 1500, "handles_type": classmethod(lambda cls, arg: False)}  # noqa: ARG005
        return type(name, (ScalarIO,), attrs)

    ios = [[make(f"IO_{t}_{i}") for i in range(per_thread)] for t in range(N_THREADS)]
    monkeypatch.setattr(_resolve, "_INSTANCE", None)

    def worker(idx: int, i: int) -> None:
        ios[idx][i].register()

    _run_in_threads(worker, iterations=per_thread)
    lost = [io.__name__ for row in ios for io in row if not is_registered(io)]
    assert lost == [], f"{len(lost)} of {N_THREADS * per_thread} registrations lost"


@pytest.mark.xfail(
    strict=True,
    raises=BaseExceptionGroup,
    reason="Shared Translator._translated_names race (_translator.py:790); xfail flips to a failure once fixed.",
)
def test_concurrent_translated_names_is_consistent(offline_translator: Translator[str, str, int]) -> None:
    """Expose the shared ``Translator._translated_names`` race (``_translator.py:790``).

    Each thread translates a single, fixed source and then reads :meth:`Translator.translated_names`,
    asserting it reflects *its own* most recent call. ``translate()`` writes ``self._translated_names``
    on a shared instance with no synchronization, so a concurrent call overwrites it between a
    thread's write and read and the assertion fails.

    .. note::

       Marked ``xfail(strict=True)``: the assertion encodes the desired (thread-safe) behaviour and is
       expected to fail on a free-threaded build today. When the shared "last call" metadata is made
       thread-safe (e.g. thread-local) or removed, the test will pass and ``strict`` turns the XPASS
       into a failure, prompting removal of this marker. Do not weaken the assertion to make it pass.
    """
    groups = [
        ({"positive_numbers": [1, 2, 3]}, {"positive_numbers"}),
        ({"negative_numbers": [-1, -2, -3]}, {"negative_numbers"}),
    ]

    def worker(idx: int, _i: int) -> None:
        inp, expected_names = groups[idx % len(groups)]
        offline_translator.translate(copy.deepcopy(inp), copy=True)
        assert set(offline_translator.translated_names()) == expected_names

    _run_in_threads(worker, iterations=500)


@pytest.mark.filterwarnings("ignore::id_translation.fetching.exceptions.ConcurrentOperationWarning")
def test_concurrent_lazy_initialization(
    online_translator: Translator[str, str, int], offline_translator: Translator[str, str, int]
) -> None:
    """Race lazy source initialization on a fresh *online* Translator.

    Concurrent ``translate()`` calls trigger concurrent ``initialize_sources()`` /
    ``_placeholders`` setup (and the non-atomic ``HexFetcher.num_fetches += 1``). This targets the
    documented not-thread-safe online path; outputs must still be correct.
    """
    expected = offline_translator.translate(copy.deepcopy(DICT_INPUT), copy=True)

    def worker(_idx: int, _i: int) -> None:
        result = online_translator.translate(copy.deepcopy(DICT_INPUT), copy=True)
        assert result == expected

    # Fewer iterations: each call hits the fetcher, which is comparatively expensive.
    _run_in_threads(worker, iterations=10)
