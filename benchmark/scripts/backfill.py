#!/usr/bin/env python
"""Backfill per-release benchmark history by running the suite against each published version.

For every release tag (>= a minimum version), this installs that ``id-translation`` release into an isolated,
ephemeral ``uv`` environment and runs the *current* benchmark harness against it (the harness degrades
gracefully on older APIs -- see ``capabilities.py``). Results land in ``benchmark/history/``.

Versions that fail to install or run (e.g. v0.10-0.12, which predate a compatible ``rics``) are skipped.

Usage::

    python scripts/backfill.py                     # all tags >= MIN_VERSION
    python scripts/backfill.py --min 1.0.0         # only 1.x
    python scripts/backfill.py --versions 1.2.0 1.2.1
    python scripts/backfill.py --python 3.11 --budget 1.0
"""

import subprocess
from pathlib import Path

import click

BENCHMARK_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BENCHMARK_DIR / "src"
REPO_DIR = BENCHMARK_DIR.parent

# Below this, id-translation pulls a rics that the current harness can't satisfy (see module docstring).
MIN_VERSION = "0.13.0"


def _version_key(v: str) -> tuple[int, ...]:
    head = v.lstrip("v").split(".dev")[0].split("rc")[0]
    return tuple(int("".join(c for c in p if c.isdigit()) or 0) for p in head.split("."))


def released_versions(minimum: str) -> list[str]:
    tags = subprocess.run(["git", "tag"], cwd=REPO_DIR, capture_output=True, text=True, check=True).stdout.split()
    versions = [t.lstrip("v") for t in tags if t.startswith("v")]
    floor = _version_key(minimum)
    return sorted({v for v in versions if _version_key(v) >= floor}, key=_version_key)


def run_one(
    version: str,
    *,
    python: str,
    budget: float,
    sizes: list[int] | None,
    history_dir: Path | None = None,
) -> bool:
    # Spin up an isolated, ephemeral env with the target release pinned alongside the suite's runtime deps
    # (the benchmark package itself is not installed -- it runs from PYTHONPATH -- so its deps go here too)...
    deps = (
        f"id-translation=={version}",
        # The suite uses the stratify performance API, which shipped in rics 6.2.0. Old id-translation releases
        # pull an older rics by default, so pin the release that provides it here.
        "rics>=6.2.0",
        "click",
        "pandas",
        "polars",
        "numpy",
    )
    uv_run = ["uv", "run", "--isolated", "--no-project", f"--python={python}", *(f"--with={dep}" for dep in deps)]

    # ...then run the *current* benchmark harness inside it, recording this version's data point.
    harness = [
        "python",
        "-m",
        "id_translation_benchmark.ci",
        f"--version={version}",
        "--save",
        "--no-progress",
        f"--budget={budget}",
    ]
    if history_dir:
        harness.append(f"--history-dir={history_dir}")
    harness += [f"--sizes={size}" for size in sizes or ()]

    cmd = [*uv_run, *harness]

    print(f"\n===== backfill v{version} =====", flush=True)
    proc = subprocess.run(
        cmd,
        cwd=REPO_DIR,
        env={"PYTHONPATH": str(SRC_DIR), "POLARS_SKIP_CPU_CHECK": "true", "PATH": _path()},
        capture_output=True,
        text=True,
        check=False,  # Non-zero is expected (old releases may not install); handled via returncode below.
    )
    if proc.returncode == 0:
        print(f"  ✓ v{version}")
        return True
    tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-4:])
    print(f"  ✗ v{version} (skipped)\n    {tail}")
    return False


def _path() -> str:
    import os

    return os.environ.get("PATH", "")


@click.command(
    help=__doc__,
    context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 120},
)
@click.option("--min", "minimum", default=MIN_VERSION, show_default=True, help="Minimum version to backfill.")
@click.option("--versions", multiple=True, help="Explicit versions (repeatable; overrides --min).")
@click.option(
    "--python",
    default="3.11",
    show_default=True,
    help="Python version for the ephemeral envs. Older releases pin deps that may lack newer-Python wheels, so "
    "3.11 maximizes historical coverage. Live release baselines are recorded on the latest supported Python.",
)
@click.option(
    "--budget",
    type=float,
    default=1.0,
    show_default=True,
    help="Timing budget (seconds) per candidate, forwarded to each release's run.",
)
@click.option("--sizes", type=int, multiple=True, help="Row counts (repeatable).")
@click.option(
    "--history-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Override the history output directory.",
)
def main(
    minimum: str,
    versions: tuple[str, ...],
    python: str,
    budget: float,
    sizes: tuple[int, ...],
    history_dir: Path | None,
) -> None:
    selected = list(versions) or released_versions(minimum)
    print(f"Backfilling {len(selected)} version(s): {', '.join(selected)}")

    ok, failed = [], []
    for version in selected:
        succeeded = run_one(
            version,
            python=python,
            budget=budget,
            sizes=list(sizes),
            history_dir=history_dir,
        )
        (ok if succeeded else failed).append(version)

    print(f"\nDone. {len(ok)} succeeded, {len(failed)} skipped.")
    if failed:
        print(f"Skipped: {', '.join(failed)}")


if __name__ == "__main__":
    main()
