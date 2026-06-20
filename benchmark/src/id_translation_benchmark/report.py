"""Render a benchmark run as Markdown (for ``$GITHUB_STEP_SUMMARY`` / PR comments) and flag regressions.

Policy: **report-only**. Regressions are flagged loudly but never fail the job -- GitHub-hosted runners are too
noisy for a hard gate. The flagging threshold is deliberately generous for the same reason.
"""

from dataclasses import dataclass
from typing import Any

# A change is only worth flagging if it clears runner noise.
REGRESS_RATIO = 1.25  # current >= 1.25x baseline  -> regression
IMPROVE_RATIO = 0.80  # current <= 0.80x baseline  -> improvement

_KEY = ("candidate", "id_type", "cardinality", "n")


@dataclass(frozen=True)
class Delta:
    """One candidate's current timing versus its baseline (if any)."""

    key: tuple[object, ...]
    current: float
    baseline: float | None

    @property
    def ratio(self) -> float | None:
        """Current / baseline, or ``None`` when there is no usable baseline."""
        if self.baseline is None or self.baseline == 0:
            return None
        return self.current / self.baseline

    @property
    def state(self) -> str:
        """Classify the delta as ``new``/``regressed``/``improved``/``same``."""
        r = self.ratio
        if r is None:
            return "new"
        if r >= REGRESS_RATIO:
            return "regressed"
        if r <= IMPROVE_RATIO:
            return "improved"
        return "same"


def _index(doc: dict[str, Any]) -> dict[tuple[object, ...], float]:
    return {tuple(rec[k] for k in _KEY): rec["ms"] for rec in doc["results"]}


def compare(current: dict[str, Any], baseline: dict[str, Any] | None) -> list[Delta]:
    """Per-key deltas of ``current`` against ``baseline`` (or no baseline)."""
    base = _index(baseline) if baseline else {}
    deltas = [Delta(key, ms, base.get(key)) for key, ms in _index(current).items()]
    # Worst regressions first; keep a stable secondary order.
    deltas.sort(key=lambda d: (-(d.ratio or 0), d.key))
    return deltas


def to_markdown(current: dict[str, Any], baseline: dict[str, Any] | None) -> str:
    """Render ``current`` (vs an optional ``baseline``) as a Markdown report."""
    deltas = compare(current, baseline)
    regressions = [d for d in deltas if d.state == "regressed"]

    lines: list[str] = []
    lines.append("## 📊 id-translation benchmark")
    lines.append("")
    lines.append(_env_line("Run", current))
    if baseline:
        lines.append(_env_line("Baseline", baseline))
    lines.append("")

    if regressions:
        lines.append(
            f"> ⚠️ **{len(regressions)} regression(s) ≥ {int((REGRESS_RATIO - 1) * 100)}%** (report-only — not gating)."
        )
    elif baseline:
        lines.append("> ✅ No significant regressions vs baseline.")
    else:
        lines.append("> ℹ️ No baseline yet — recording first data point.")
    lines.append("")

    header = "| | candidate | id_type | card | n | current (ms) | baseline (ms) | Δ |"
    lines.append(header)
    lines.append("|---|---|---|---|--:|--:|--:|--:|")
    for d in deltas:
        candidate, id_type, card, n = d.key
        lines.append(
            f"| {_emoji(d.state)} | `{candidate}` | {id_type} | {card} | {n:,} "
            f"| {d.current:.2f} | {_fmt(d.baseline)} | {_fmt_delta(d)} |"
        )
    lines.append("")
    return "\n".join(lines)


def _env_line(label: str, doc: dict[str, Any]) -> str:
    bits = [f"**{label}:** v{doc['version']}"]
    bits.extend(f"{k} {doc[k]}" for k in ("python", "pandas", "polars", "platform") if doc.get(k))
    return " · ".join(bits)


def _emoji(state: str) -> str:
    return {"regressed": "🔴", "improved": "🟢", "new": "🆕", "same": "⚪"}[state]


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _fmt_delta(d: Delta) -> str:
    r = d.ratio
    if r is None:
        return "—"
    pct = (r - 1) * 100
    return f"{pct:+.0f}%"
