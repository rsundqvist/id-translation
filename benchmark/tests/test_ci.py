"""Tests for the history serialization and regression report."""

import pandas as pd

from id_translation_benchmark.history import (
    best_records,
    build_history,
    latest_baseline,
    load_all,
    save_history,
)
from id_translation_benchmark.report import REGRESS_RATIO, compare, to_markdown


def _doc(version, results):
    return {"version": version, "python": "3.11.0", "results": results}


def _rec(candidate="pandas.Series", id_type="int", cardinality="low", n=1000, ms=10.0):
    return {"candidate": candidate, "id_type": id_type, "cardinality": cardinality, "n": n, "ms": ms}


def test_best_records_takes_min_per_key():
    df = pd.DataFrame(
        {
            "Candidate": ["pandas.Series", "pandas.Series", "polars.Series"],
            "n": [1000, 1000, 1000],
            "cardinality": ["low", "low", "low"],
            "id_type": ["int", "int", "int"],
            "Time [ms]": [12.0, 9.0, 5.0],  # two repeats for pandas -> min 9.0
        }
    )
    records = best_records(df)
    by_candidate = {r["candidate"]: r["ms"] for r in records}
    assert by_candidate == {"pandas.Series": 9.0, "polars.Series": 5.0}


def test_build_history_has_schema():
    df = pd.DataFrame(
        {"Candidate": ["pandas.Series"], "n": [1000], "cardinality": ["low"], "id_type": ["int"], "Time [ms]": [3.0]}
    )
    doc = build_history(df, version="9.9.9")
    assert doc["version"] == "9.9.9"
    assert doc["unit"] == "ms"
    assert doc["results"] == [_rec(ms=3.0)]


def test_compare_states():
    base = _doc(
        "1.0.0",
        [
            _rec(id_type="int", ms=100.0),
            _rec(id_type="str", ms=100.0),
            _rec(id_type="uuid-str", ms=100.0),
        ],
    )
    cur = _doc(
        "1.1.0",
        [
            _rec(id_type="int", ms=200.0),  # regressed (2x)
            _rec(id_type="str", ms=50.0),  # improved
            _rec(id_type="uuid-str", ms=105.0),  # same (within noise)
            _rec(id_type="int", cardinality="high", ms=7.0),  # new key
        ],
    )
    states = {d.key: d.state for d in compare(cur, base)}
    assert states[("pandas.Series", "int", "low", 1000)] == "regressed"
    assert states[("pandas.Series", "str", "low", 1000)] == "improved"
    assert states[("pandas.Series", "uuid-str", "low", 1000)] == "same"
    assert states[("pandas.Series", "int", "high", 1000)] == "new"


def test_compare_no_baseline_is_all_new():
    cur = _doc("1.0.0", [_rec(), _rec(id_type="str")])
    assert {d.state for d in compare(cur, None)} == {"new"}


def test_markdown_flags_regression_and_is_report_only():
    base = _doc("1.0.0", [_rec(ms=100.0)])
    cur = _doc("1.1.0", [_rec(ms=100.0 * (REGRESS_RATIO + 0.1))])
    md = to_markdown(cur, base)
    assert "regression" in md.lower()
    assert "not gating" in md.lower()
    assert "🔴" in md


def test_history_roundtrip_and_baseline_ordering(tmp_path):
    save_history(_doc("1.9.0", [_rec()]), tmp_path)
    save_history(_doc("1.10.0", [_rec(ms=11.0)]), tmp_path)  # numerically newer than 1.9.0
    save_history(_doc("1.2.1.dev1", [_rec(ms=12.0)]), tmp_path)

    versions = [d["version"] for d in load_all(tmp_path)]
    assert versions.index("1.9.0") < versions.index("1.10.0")

    assert latest_baseline(tmp_path)["version"] == "1.10.0"
    assert latest_baseline(tmp_path, exclude="1.10.0")["version"] == "1.9.0"
