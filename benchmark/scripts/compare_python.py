#!/usr/bin/env python
"""Compare two backfilled history sets recorded on different Python interpreters.

Given two directories of ``v<version>.json`` files (one per interpreter), report the per-release timing
differences on the versions present in *both*. Ratios are ``new / old``; ``< 1`` means the *new* interpreter is
faster. Only the IO layer is timed (see the benchmark README), and both sets should come from the same machine so
the interpreter is the only moving part.

Usage::

    python scripts/compare_python.py --old results/python-compare/py311 --new results/python-compare/py314
"""

import math
import sys
from pathlib import Path
from statistics import median
from typing import Any

import click

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from id_translation_benchmark.history import _version_key, load_all
from id_translation_benchmark.report import _KEY

# Outside this band a difference is worth calling out; within it, it is interpreter/runner noise.
FASTER = 0.95
SLOWER = 1.05


def _index(doc: dict[str, Any]) -> dict[tuple, float]:
    return {tuple(rec[k] for k in _KEY): rec["ms"] for rec in doc["results"]}


def _geomean(ratios: list[float]) -> float:
    return math.exp(sum(map(math.log, ratios)) / len(ratios)) if ratios else float("nan")


def _label(docs: list[dict[str, Any]]) -> str:
    pys = sorted({d.get("python", "?") for d in docs})
    return pys[0] if len(pys) == 1 else "/".join(pys)


@click.command(
    help=__doc__,
    context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 120},
)
@click.option("--old", type=click.Path(exists=True, file_okay=False, path_type=Path), required=True,
              help="History dir for the baseline interpreter.")
@click.option("--new", type=click.Path(exists=True, file_okay=False, path_type=Path), required=True,
              help="History dir for the new interpreter.")
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Write the Markdown report here (also printed).")
def main(old: Path, new: Path, out: Path | None) -> None:
    old_docs = load_all(old)
    new_docs = load_all(new)
    old = {d["version"]: d for d in old_docs}
    new = {d["version"]: d for d in new_docs}
    overlap = sorted(set(old) & set(new), key=_version_key)

    old_py, new_py = _label(old_docs), _label(new_docs)

    lines: list[str] = []
    lines.append(f"## 🐍 Python {old_py} → {new_py}: per-release benchmark deltas")
    lines.append("")
    lines.append(
        f"Ratio = `new / old` (Python {new_py} vs {old_py}); **< 1.00 means {new_py} is faster**. "
        f"Same machine, same pandas/polars — interpreter is the only variable. "
        f"Overlapping versions: **{len(overlap)}** of {len(old)} ({old_py}) / {len(new)} ({new_py})."
    )
    lines.append("")
    only_old = sorted(set(old) - set(new), key=_version_key)
    only_new = sorted(set(new) - set(old), key=_version_key)
    if only_old:
        lines.append(f"> Only on {old_py} (no {new_py} wheels / install failed): {', '.join('v' + v for v in only_old)}")
    if only_new:
        lines.append(f"> Only on {new_py}: {', '.join('v' + v for v in only_new)}")

    # The interpreter is only the *sole* variable if the resolved pandas/polars match for a version.
    mismatched = []
    for version in overlap:
        for lib in ("pandas", "polars"):
            if old[version].get(lib) != new[version].get(lib):
                mismatched.append(f"v{version}: {lib} {old[version].get(lib)}→{new[version].get(lib)}")
    if mismatched:
        lines.append(f"> ⚠️ Dependency version differs (not pure interpreter): {'; '.join(mismatched)}")
    if only_old or only_new or mismatched:
        lines.append("")

    # Per-version summary.
    lines.append("### Per-version summary")
    lines.append("")
    lines.append("| version | keys | geomean | median | faster | slower | best | worst |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    all_ratios: list[float] = []
    per_candidate: dict[str, list[float]] = {}
    for version in overlap:
        o, n = _index(old[version]), _index(new[version])
        ratios = []
        for key in o.keys() & n.keys():
            if o[key] > 0:
                r = n[key] / o[key]
                ratios.append(r)
                all_ratios.append(r)
                per_candidate.setdefault(key[0], []).append(r)
        if not ratios:
            continue
        faster = sum(r < FASTER for r in ratios)
        slower = sum(r > SLOWER for r in ratios)
        lines.append(
            f"| v{version} | {len(ratios)} | {_geomean(ratios):.2f} | {median(ratios):.2f} "
            f"| {faster} | {slower} | {min(ratios):.2f} | {max(ratios):.2f} |"
        )

    # Per-backend aggregate across all overlapping versions.
    lines.append("")
    lines.append("### By backend (all overlapping versions)")
    lines.append("")
    lines.append("| candidate | samples | geomean | median |")
    lines.append("|---|--:|--:|--:|")
    for candidate in sorted(per_candidate):
        rs = per_candidate[candidate]
        lines.append(f"| `{candidate}` | {len(rs)} | {_geomean(rs):.2f} | {median(rs):.2f} |")

    lines.append("")
    if all_ratios:
        gm = _geomean(all_ratios)
        verdict = f"{new_py} is {1 / gm:.2f}x faster" if gm < 1 else f"{new_py} is {gm:.2f}x slower"
        lines.append(f"**Overall geomean: {gm:.3f}** ({verdict} across {len(all_ratios)} measurements).")
    lines.append("")

    report = "\n".join(lines)
    print(report)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report + "\n")
        print(f"\nWrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
