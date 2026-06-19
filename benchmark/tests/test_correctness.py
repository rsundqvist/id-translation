"""Sanity checks: a benchmark is meaningless if the operation it times is wrong.

These verify that every backend actually produces correct translations for every ID type, on data small
enough to assert exactly. Run with ``pytest`` from the ``benchmark/`` directory.
"""

import pytest

from id_translation_benchmark.backends import BACKENDS
from id_translation_benchmark.data import SOURCE, ID_TYPES, make_ids, unique_ids
from id_translation_benchmark.payload import build_payload
from id_translation_benchmark.suite import Config, run


def _expected(ids) -> list[str]:
    return [f"{i}:name-of-{i}" for i in ids.tolist()]


def _actual(translated, backend: str) -> list[str]:
    """Normalize a translated container into a flat list of strings."""
    if backend in {"pandas.Series", "pandas.Index"}:
        return list(translated)
    if backend == "pandas.DataFrame":
        return translated[SOURCE].tolist()
    if backend == "polars.Series":
        return translated.to_list()
    if backend == "polars.DataFrame":
        return translated[SOURCE].to_list()
    if backend == "dict":
        return translated[SOURCE]
    if backend == "set":
        return sorted(translated)
    return list(translated)  # list / tuple


@pytest.mark.parametrize("backend", list(BACKENDS))
@pytest.mark.parametrize("id_type", ID_TYPES)
def test_backend_translates_correctly(backend: str, id_type) -> None:
    ids = make_ids(20, n_unique=5, id_type=id_type)
    payload = build_payload(n=20, n_unique=5, id_type=id_type, backends=[backend])

    translated = payload.translate(backend)
    actual = _actual(translated, backend)

    if backend == "set":
        expected = sorted(set(_expected(ids)))
    else:
        expected = _expected(ids)
    assert actual == expected


def test_cardinality_is_respected() -> None:
    ids = make_ids(10_000, n_unique=50, id_type="int")
    assert len(unique_ids(ids)) == 50
    assert len(ids) == 10_000

    all_unique = make_ids(1_000, n_unique=None, id_type="int")
    assert len(unique_ids(all_unique)) == 1_000


def test_run_returns_tidy_frame() -> None:
    df = run(Config(sizes=[500], id_types=["int"], time_per_candidate=0.05, repeat=2), progress=False)
    for col in ("backend", "n", "cardinality", "id_type", "Time [ms]"):
        assert col in df.columns
    assert set(df["backend"]) == set(Config().backends)
