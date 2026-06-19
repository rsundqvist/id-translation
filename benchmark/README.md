# id-translation benchmark suite

Measures [`Translator.translate`][translate] across container backends, ID types, dataset sizes and
cardinalities. The headline use-case is **large datasets with vectorized types** (pandas / polars); the Python
builtins (`list`/`tuple`/`dict`/`set`) are kept as a non-vectorized baseline.

[translate]: https://id-translation.readthedocs.io/

## What it measures

| Dimension       | Values                                                                            |
|-----------------|-----------------------------------------------------------------------------------|
| backend         | `pandas.Series/Index/DataFrame`, `polars.Series/DataFrame`, `list/tuple/dict/set` |
| id_type         | `int`, `str`, `uuid-str` (stringified UUID), `uuid` (object-dtype path)            |
| size `n`        | rows, the headline scaling axis                                                    |
| cardinality     | `low` (~1k distinct) and `high` (all distinct)                                     |
| IO knobs        | `PandasIO(as_category=...)`, `PolarsIO(fast=...)` via the `knobs` suite            |

Translation runs **offline** (the ID universe is pre-fetched into an in-memory map) so timings are dominated by
the backend-specific vectorized work — extracting unique IDs and broadcasting translations back onto every row —
rather than by fetching.

## Design

```
data.py         generate ID arrays (n / cardinality / id_type)
backends.py     wrap an ID array in a concrete container type
payload.py      build the offline Translator + containers for one case (outside the timed region)
suite.py        Candidate (backend + io_kwargs) x data grid -> rics.MultiCaseTimer -> tidy DataFrame
capabilities.py feature-detect the installed id_translation version (for backfill compatibility)
cli.py          run, write results.csv + summary.csv, optional plots
history.py      portable config + per-release JSON (de)serialization
report.py       Markdown report + regression flagging (report-only)
ci.py           CI entry point: run -> render report -> optionally --save history
scripts/        backfill.py: run the suite against each released version
```

A *candidate* is a `(backend, io_kwargs)` pair, so the suite can compare not just pandas-vs-polars but the IO
knobs that move performance. Results come back as a tidy DataFrame via [`rics.performance`][rics], ready for
`plot_run` / `get_best`.

[rics]: https://rics.readthedocs.io/en/stable/_autosummary/rics.performance.html

## Running

```bash
cd benchmark
uv run id-translation-benchmark --quick            # fast smoke test
uv run id-translation-benchmark                     # headline: pandas vs polars, large vectorized data
uv run id-translation-benchmark --suite knobs       # default vs as_category / fast
uv run id-translation-benchmark --suite all --plot  # + builtins baseline + plots (needs the 'plot' extra)
```

Without installing, from the repo's dev environment:

```bash
PYTHONPATH=src python -m id_translation_benchmark --quick
```

Useful flags: `--sizes 10000 --sizes 1000000`, `--id-types int --id-types str`, `--cardinality {low,high,both}`,
`--budget`, `--repeat`, `--output DIR`. (`--sizes` and `--id-types` are repeatable.)

`--budget` is the per-candidate timing budget (seconds). By default the suite stratifies by size, so each size gets its
own calibrated iteration count and small sizes aren't under-sampled when run alongside large ones; pass `--no-stratify`
for the old shared-budget behavior. Stratification needs a `rics` that supports `MultiCaseTimer.run(stratify=...)`.

## Output

* `results.csv` — one row per timed repeat (raw, for your own analysis).
* `summary.csv` — best (min) time per backend × data variant, pivoted.
* `plot_<id_type>.png` — with `--plot`.

## CI, history & regression reports

A `benchmark` GitHub Actions workflow tracks performance over time.

* **Pull requests / pushes** run a small, portable config (`int` / `str` / `uuid-str` on
  pandas & polars `Series`/`DataFrame`, default settings) and render a report comparing the run to the latest
  recorded release — posted to the **job summary** and as a sticky **PR comment**.
* **Release tags (`v*`)** record the version's data point to `benchmark/history/v<version>.json` (committed to
  master).
* Regressions are **report-only** (flagged 🔴, never failing the job) — GitHub-hosted runners are too noisy for a
  hard gate.

The report and history come from `python -m id_translation_benchmark.ci` (run + render + optional `--save`).

### Per-release history & backfill

History lives as one JSON per release under `benchmark/history/`. The harness degrades gracefully on older APIs
(see `capabilities.py`), so it can run against past releases:

```bash
python benchmark/scripts/backfill.py --min 0.13.0   # one isolated env per release
```

Backfill is feasible from **v0.13.0+** (earlier releases predate a compatible `rics`). Generate history on a
**consistent environment** — run the `benchmark` workflow via *workflow_dispatch* with `backfill=true` so all
data points come from the CI runner (local timings are machine-specific and make a poor baseline).

## Correctness

`tests/` asserts every backend translates correctly for every ID type before any timing is trusted. Run with
`uv run pytest` (or `PYTHONPATH=src pytest`).

See [FINDINGS.md](FINDINGS.md) for results and the performance opportunities this suite surfaced in the IO layer.
