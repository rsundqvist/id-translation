"""Feature detection for the *installed* ``id_translation`` version.

The suite is run against many historical releases (see ``scripts/backfill.py``), so it must degrade gracefully
when an API does not exist yet rather than crashing. Detection is by introspection, not version parsing.
"""

import inspect
from functools import cache

import id_translation
from id_translation import Translator


@cache
def version() -> str:
    return id_translation.__version__


@cache
def supports_stratify() -> bool:
    """``MultiCaseTimer.run(..., stratify=...)`` exists (calibrates ``number`` per stratum, not per candidate)."""
    from rics.performance import MultiCaseTimer  # noqa: PLC0415

    return "stratify" in inspect.signature(MultiCaseTimer.run).parameters


@cache
def supports_io_kwargs() -> bool:
    """``Translator.translate(..., io_kwargs=...)`` exists (since 1.1.0)."""
    return "io_kwargs" in inspect.signature(Translator.translate).parameters


@cache
def supports_enable_uuid_heuristics() -> bool:
    """``Translator(enable_uuid_heuristics=...)`` exists (since 0.4.0)."""
    return "enable_uuid_heuristics" in inspect.signature(Translator.__init__).parameters


@cache
def available_backends() -> set[str]:
    """Backend names whose dependency imports and whose DIO is registered for the installed version."""
    from .backends import BACKENDS  # noqa: PLC0415

    available: set[str] = set()
    for name, backend in BACKENDS.items():
        module = name.split(".", 1)[0]
        if module in {"pandas", "polars"}:
            try:
                __import__(module)
            except ImportError:
                continue
        available.add(name)
    return available
