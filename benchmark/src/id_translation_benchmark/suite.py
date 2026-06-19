"""Benchmark configuration and execution.

A run compares **candidates** across a grid of data variants. A candidate is a ``(backend, io_kwargs)`` pair --
this lets us measure not just pandas-vs-polars, but the IO knobs that have a large effect on performance:
:class:`~id_translation.dio.integration.pandas.PandasIO` ``as_category`` and
:class:`~id_translation.dio.integration.polars.PolarsIO` ``fast``.

The data grid is the cartesian product of ``sizes`` x ``cardinalities`` x ``id_types``. Results come back as a
tidy :class:`pandas.DataFrame` (via :func:`rics.performance.to_dataframe`) with one column per dimension, ready
for :func:`rics.performance.plot_run` / :func:`rics.performance.get_best`.
"""

from dataclasses import dataclass, field
from itertools import product

import pandas as pd
from rics.performance import MultiCaseTimer, to_dataframe

from .backends import VECTORIZED
from .capabilities import supports_stratify
from .data import ID_TYPES, IdType
from .payload import build_payload

# Data dimension column names, in case-arg order. Consumed by ``to_dataframe(names=...)``.
DIMENSIONS = ["n", "cardinality", "id_type"]

# Named cardinalities. ``None`` => all-unique (n_unique == n), the high-cardinality stress case.
CARDINALITIES: dict[str, int | None] = {"low": 1_000, "high": None}


@dataclass(frozen=True)
class Candidate:
    """One thing to time: a backend, optionally with IO knobs applied."""

    label: str
    backend: str
    io_kwargs: dict | None = None
    skip_id_types: frozenset[str] = frozenset()
    """ID types this candidate cannot handle (skipped instead of erroring)."""

    @classmethod
    def of(cls, backend: str, *, skip_id_types: frozenset[str] = frozenset(), **io_kwargs: object) -> "Candidate":
        """Build a candidate, deriving a ``backend[knob=value]`` label from the IO kwargs."""
        if not io_kwargs:
            return cls(backend, backend, skip_id_types=skip_id_types)
        knobs = ",".join(f"{k}={v}" for k, v in io_kwargs.items())
        return cls(f"{backend}[{knobs}]", backend, dict(io_kwargs), skip_id_types=skip_id_types)


def default_candidates(backends: list[str]) -> list[Candidate]:
    """Each backend at its default settings."""
    return [Candidate.of(b) for b in backends]


@dataclass
class Config:
    """Defines one benchmark run."""

    candidates: list[Candidate] = field(default_factory=lambda: default_candidates(list(VECTORIZED)))
    sizes: list[int] = field(default_factory=lambda: [10_000, 1_000_000, 10_000_000])
    cardinalities: dict[str, int | None] = field(default_factory=lambda: dict(CARDINALITIES))
    id_types: list[IdType] = field(default_factory=lambda: list(ID_TYPES))
    time_per_candidate: float = 2.0
    repeat: int = 3
    stratify_by_size: bool = True
    """Calibrate the timing iteration count per size, so small sizes aren't under-sampled when measured alongside
    large ones. Requires a rics that supports ``MultiCaseTimer.run(stratify=...)``; ignored otherwise."""

    @property
    def backends(self) -> list[str]:
        """The distinct backends referenced by the candidates (containers to materialize)."""
        return list(dict.fromkeys(c.backend for c in self.candidates))

    def case_args(self) -> list[tuple[int, str, IdType]]:
        """The data grid as ``(n, cardinality_label, id_type)`` tuples."""
        return [
            (n, label, id_type)
            for n, label, id_type in product(self.sizes, self.cardinalities, self.id_types)
        ]


def build_timer(config: Config) -> MultiCaseTimer:
    """Create a :class:`~rics.performance.MultiCaseTimer` for ``config``."""
    backends = config.backends

    def factory(n: int, cardinality: str, id_type: IdType):
        return build_payload(
            n=n,
            n_unique=config.cardinalities[cardinality],
            id_type=id_type,
            backends=backends,
        )

    candidates = {c.label: _make_candidate(c) for c in config.candidates}
    return MultiCaseTimer(candidates, factory, case_args=config.case_args())


def _make_skip_if(config: Config):
    """Skip ``(candidate, data)`` combos a candidate declares it cannot handle (e.g. polars fast=True + uuid)."""
    by_label = {c.label: c for c in config.candidates}

    def skip_if(params) -> bool:
        candidate = by_label[params.candidate_label]
        _n, _cardinality, id_type = params.data_label
        return id_type in candidate.skip_id_types

    return skip_if


def run(config: Config, *, progress: bool = True) -> pd.DataFrame:
    """Execute ``config`` and return a tidy results DataFrame."""
    timer = build_timer(config)
    run_kwargs = dict(
        time_per_candidate=config.time_per_candidate,
        repeat=config.repeat,
        progress=progress,
        skip_if=_make_skip_if(config),
    )
    if config.stratify_by_size and supports_stratify():
        # case_args are (n, cardinality, id_type); stratify by n so each size gets its own calibrated iteration count.
        run_kwargs["stratify"] = lambda label: label[0]
    raw = timer.run(**run_kwargs)
    # Keep the ``Candidate`` column name so rics tooling (plot_run/get_best) stays compatible;
    # add a friendlier ``backend`` alias alongside it.
    df = to_dataframe(raw, names=DIMENSIONS)
    df.insert(0, "backend", df["Candidate"])
    return df


def _make_candidate(candidate: Candidate):
    # Bind the spec so each candidate translates its own backend's container with its IO kwargs.
    # Short-circuit unsupported id types to a no-op: rics' autonumber phase calls every candidate on every
    # data variant *without* consulting skip_if, so an erroring candidate would otherwise break the whole run.
    # skip_if (see _make_skip_if) keeps these no-op combos out of the recorded results.
    def candidate_fn(payload):
        if payload.id_type in candidate.skip_id_types:
            return None
        return payload.translate(candidate.backend, candidate.io_kwargs)

    return candidate_fn
