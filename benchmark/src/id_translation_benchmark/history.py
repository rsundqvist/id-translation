"""Per-release performance history: a portable config + JSON (de)serialization.

The history config is deliberately small and **portable** so the same measurement runs against every backfilled
release: default-settings candidates (no IO knobs, which only exist from 1.1.0) on the vectorized int / str /
stringified-UUID types. One JSON file per version lives under ``benchmark/history/``.
"""

import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .capabilities import available_backends, version as installed_version
from .suite import Config, default_candidates

HISTORY_DIR = Path(__file__).resolve().parents[2] / "history"  # benchmark/history/

# Tracked across all releases: native int, generic strings, and the common "UUID stored as a string" case.
HISTORY_ID_TYPES = ["int", "str", "uuid-str"]

# Series + DataFrame for both engines. Portable (default settings) so it is comparable across versions.
_HISTORY_BACKENDS = ["pandas.Series", "pandas.DataFrame", "polars.Series", "polars.DataFrame"]


def history_config(
    *,
    sizes: list[int] | None = None,
    time_per_candidate: float = 1.0,
    repeat: int = 3,
) -> Config:
    """The portable config tracked over time, restricted to backends the installed version supports."""
    backends = [b for b in _HISTORY_BACKENDS if b in available_backends()]
    return Config(
        candidates=default_candidates(backends),
        sizes=sizes or [1_000_000],
        cardinalities={"low": 1_000, "high": None},
        id_types=HISTORY_ID_TYPES,
        time_per_candidate=time_per_candidate,
        repeat=repeat,
    )


def best_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Collapse raw timings to the best (min) ms per ``(candidate, n, cardinality, id_type)``."""
    keys = ["Candidate", "n", "cardinality", "id_type"]
    best = df.groupby(keys, sort=True)["Time [ms]"].min().reset_index(name="ms")
    return [
        {
            "candidate": row.Candidate,
            "n": int(row.n),
            "cardinality": row.cardinality,
            "id_type": row.id_type,
            "ms": round(float(row.ms), 4),
        }
        for row in best.itertuples(index=False)
    ]


def metadata() -> dict[str, Any]:
    """Environment fingerprint stored alongside results."""
    meta: dict[str, Any] = {
        "id_translation": installed_version(),
        "python": platform.python_version(),
        "platform": platform.system(),
        "machine": platform.machine(),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "unit": "ms",
    }
    for mod in ("pandas", "polars"):
        try:
            meta[mod] = __import__(mod).__version__
        except ImportError:
            meta[mod] = None
    return meta


def build_history(df: pd.DataFrame, *, version: str | None = None) -> dict[str, Any]:
    """Assemble the JSON document for one run."""
    return {
        "version": version or installed_version(),
        **metadata(),
        "results": best_records(df),
    }


def save_history(doc: dict[str, Any], directory: Path = HISTORY_DIR) -> Path:
    """Write ``doc`` to ``<directory>/v<version>.json`` and return the path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"v{doc['version']}.json"
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return path


def load_history(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def load_all(directory: Path = HISTORY_DIR) -> list[dict[str, Any]]:
    """All history docs, sorted oldest-first by version."""
    docs = [load_history(p) for p in Path(directory).glob("v*.json")]
    return sorted(docs, key=lambda d: _version_key(d["version"]))


def latest_baseline(directory: Path = HISTORY_DIR, *, exclude: str | None = None) -> dict[str, Any] | None:
    """The newest history doc, optionally excluding ``exclude`` (e.g. the version being measured now)."""
    docs = [d for d in load_all(directory) if d["version"] != exclude]
    return docs[-1] if docs else None


def _version_key(v: str) -> tuple:
    # Sort 1.10.0 after 1.9.0; ignore any dev/rc suffix on the numeric head.
    head = v.split(".dev")[0].split("rc")[0].split("+")[0]
    parts = []
    for piece in head.split("."):
        digits = "".join(c for c in piece if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


if __name__ == "__main__":  # pragma: no cover - convenience for CI/backfill.
    from .suite import run

    argv = sys.argv[1:]
    ver = argv[0] if argv else None
    document = build_history(run(history_config(), progress=False), version=ver)
    out = save_history(document)
    print(f"Wrote {out} ({len(document['results'])} records, id_translation={document['id_translation']}).")
