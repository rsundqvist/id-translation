"""CI entry point: run the portable history config, render a report, optionally persist the JSON.

Usage::

    # PR / push: measure current code, compare to the latest recorded release, write a report (no commit).
    python -m id_translation_benchmark.ci

    # Release: record this version's data point under benchmark/history/.
    python -m id_translation_benchmark.ci --version 1.2.1 --save

The report is written to ``$GITHUB_STEP_SUMMARY`` when present, to ``--report-file`` if given, and to stdout.
"""

import os
from pathlib import Path

import click

from .history import HISTORY_DIR, build_history, history_config, latest_baseline, save_history
from .report import to_markdown
from .suite import run


@click.command(
    context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 120},
)
@click.option("--version", default=None, help="Label for this run (default: installed id_translation version).")
@click.option("--save", is_flag=True, help="Persist the run to <history-dir>/v<version>.json.")
@click.option("--history-dir", type=click.Path(file_okay=False, path_type=Path), default=HISTORY_DIR, show_default=True)
@click.option("--sizes", type=int, multiple=True, help="Row counts (repeatable; default: history config).")
@click.option(
    "--budget",
    type=float,
    default=1.0,
    show_default=True,
    help="Timing budget (seconds) per candidate. The history config uses a single size, so the whole "
    "budget goes to it; raise it for steadier numbers.",
)
@click.option("--repeat", type=int, default=3, show_default=True)
@click.option(
    "--report-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Also write the Markdown report here.",
)
@click.option("--no-progress", is_flag=True)
def main(
    version: str | None,
    save: bool,
    history_dir: Path,
    sizes: tuple[int, ...],
    budget: float,
    repeat: int,
    report_file: Path | None,
    no_progress: bool,
) -> None:
    """Run the portable history benchmark and render a regression report."""
    config = history_config(
        sizes=list(sizes) or None,
        time_per_candidate=budget,
        repeat=repeat,
    )
    print(f"Running history config: {[c.label for c in config.candidates]} x {config.id_types} @ {config.sizes}")
    df = run(config, progress=not no_progress)
    doc = build_history(df, version=version)

    baseline = latest_baseline(history_dir, exclude=doc["version"])
    markdown = to_markdown(doc, baseline)

    if save:
        path = save_history(doc, history_dir)
        print(f"Saved history -> {path}")

    _emit(markdown, report_file)


def _emit(markdown: str, report_file: Path | None) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as fh:
            fh.write(markdown + "\n")
    if report_file:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(markdown + "\n")
    print("\n" + markdown)


if __name__ == "__main__":
    main()
