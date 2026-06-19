"""Command-line entry point for the benchmark suite.

Examples::

    # Headline run: pandas vs polars on large vectorized data.
    python -m id_translation_benchmark

    # Quick smoke test.
    python -m id_translation_benchmark --quick

    # Include the builtin baseline (list/tuple/dict/set) and write plots.
    python -m id_translation_benchmark --suite all --plot
"""

from pathlib import Path

import click

from .backends import BASELINE, VECTORIZED
from .data import ID_TYPES
from .suite import CARDINALITIES, Candidate, Config, default_candidates, run


def _cardinalities(choice: str) -> dict[str, int | None]:
    if choice == "both":
        return dict(CARDINALITIES)
    return {choice: CARDINALITIES[choice]}


_KNOBS_CANDIDATES = [
    Candidate.of("pandas.Series"),
    Candidate.of("pandas.Series", as_category=True),
    Candidate.of("polars.Series"),
    # fast=True forwards a UUID-keyed dict to replace_strict, which cannot build a polars Series of
    # objects -> unsupported for the uuid id type.
    Candidate.of("polars.Series", fast=True, skip_id_types=frozenset({"uuid"})),
]


def _groups() -> dict[str, tuple[list[Candidate], list[int]]]:
    return {
        "vectorized": (default_candidates(list(VECTORIZED)), [10_000, 1_000_000, 10_000_000]),
        "builtins": (default_candidates(list(BASELINE)), [10_000, 100_000, 1_000_000]),
        "knobs": (_KNOBS_CANDIDATES, [10_000, 1_000_000, 10_000_000]),
    }


def _configs(
    *,
    suite: str,
    sizes: list[int] | None,
    id_types: list[str],
    cardinality: str,
    budget: float,
    repeat: int,
    stratify: bool,
    quick: bool,
) -> dict[str, Config]:
    cardinalities = _cardinalities(cardinality)
    common = dict(
        cardinalities=cardinalities,
        id_types=id_types,
        time_per_candidate=budget,
        repeat=repeat,
        stratify_by_size=stratify,
    )
    if quick:
        return {"quick": Config(sizes=sizes or [1_000, 50_000], time_per_candidate=0.3, repeat=2,
                                cardinalities=cardinalities, id_types=id_types, stratify_by_size=stratify)}

    groups = _groups()
    selected = ["vectorized", "builtins"] if suite == "all" else [suite]
    return {
        name: Config(candidates=candidates, sizes=sizes or default_sizes, **common)
        for name in selected
        for candidates, default_sizes in [groups[name]]
    }


@click.command(
    context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 120},
)
@click.option(
    "--suite",
    type=click.Choice(["vectorized", "builtins", "knobs", "all"]),
    default="vectorized",
    show_default=True,
    help=(
        "vectorized: pandas/polars containers at default settings. "
        "builtins: list/tuple/dict/set baseline (smaller sizes). "
        "knobs: default vs IO knobs (pandas as_category, polars fast). "
        "all: vectorized + builtins."
    ),
)
@click.option("--sizes", type=int, multiple=True, help="Row counts (repeatable; overrides suite defaults).")
@click.option(
    "--id-types",
    "id_types",
    type=click.Choice(ID_TYPES),
    multiple=True,
    default=tuple(ID_TYPES),
    show_default=True,
    help="ID type(s) to benchmark (repeatable).",
)
@click.option(
    "--cardinality",
    type=click.Choice([*CARDINALITIES, "both"]),
    default="both",
    show_default=True,
    help="'low' (~1k distinct), 'high' (all distinct), or 'both'.",
)
@click.option("--budget", type=float, default=2.0, show_default=True,
              help="Timing budget (seconds) per candidate. With --stratify (default) it applies per candidate per "
                   "size; otherwise it is shared across the whole data grid, so adding variants gives each one less "
                   "time. Raise it for steadier numbers.")
@click.option("--stratify/--no-stratify", default=True, show_default=True,
              help="Calibrate the timing iteration count per size, so small sizes aren't under-sampled (hence noisy) "
                   "when measured alongside large ones. No-op on a rics without stratify support.")
@click.option("--repeat", type=int, default=3, show_default=True)
@click.option("--output", type=click.Path(file_okay=False, path_type=Path), default=Path("results"),
              show_default=True, help="Directory for CSV (and plot) output.")
@click.option("--plot", is_flag=True, help="Write plots (requires the 'plot' extra: seaborn).")
@click.option("--no-progress", is_flag=True)
@click.option("--quick", is_flag=True, help="Tiny, fast run for smoke-testing the suite itself.")
def main(
    suite: str,
    sizes: tuple[int, ...],
    id_types: tuple[str, ...],
    cardinality: str,
    budget: float,
    stratify: bool,
    repeat: int,
    output: Path,
    plot: bool,
    no_progress: bool,
    quick: bool,
) -> None:
    """Benchmark Translator.translate across container backends and data sizes."""
    output.mkdir(parents=True, exist_ok=True)

    import pandas as pd

    configs = _configs(
        suite=suite,
        sizes=list(sizes) or None,
        id_types=list(id_types),
        cardinality=cardinality,
        budget=budget,
        repeat=repeat,
        stratify=stratify,
        quick=quick,
    )
    frames = []
    for name, config in configs.items():
        print(f"\n=== Running suite: {name} ===")
        print(f"backends={config.backends}")
        print(f"sizes={config.sizes} cardinalities={list(config.cardinalities)} id_types={config.id_types}")
        df = run(config, progress=not no_progress)
        df.insert(0, "suite", name)
        frames.append(df)

    results = pd.concat(frames, ignore_index=True)
    results_path = output / "results.csv"
    results.to_csv(results_path, index=False)
    print(f"\nWrote raw results -> {results_path}")

    summary = _summarize(results)
    summary_path = output / "summary.csv"
    summary.to_csv(summary_path)
    print(f"Wrote summary     -> {summary_path}\n")
    print(summary.to_string())

    if plot:
        _plot(results, output)


def _summarize(results):
    """Best (min) time per backend x data variant, pivoted for readability."""
    keys = ["n", "id_type", "cardinality", "backend"]
    best = results.groupby(keys, sort=True)["Time [ms]"].min().reset_index()
    return best.pivot_table(
        index=["n", "id_type", "cardinality"], columns="backend", values="Time [ms]"
    ).round(3)


def _plot(results, output: Path) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        from rics.performance import plot_run
    except ModuleNotFoundError as e:
        print(f"Plotting skipped ({e.name} not installed). Install the 'plot' extra: pip install -e '.[plot]'")
        return

    for id_type, group in results.groupby("id_type"):
        grid = plot_run(group, x="candidate")
        grid.figure.suptitle(f"Translator.translate -- id_type={id_type}", y=1.02)
        path = output / f"plot_{id_type}.png"
        grid.savefig(path, dpi=100, bbox_inches="tight")
        print(f"Wrote plot        -> {path}")


if __name__ == "__main__":
    main()
