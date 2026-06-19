"""Benchmark suite for :mod:`id_translation`.

Focus: **large datasets with vectorized types** (pandas / polars). Python builtins are a baseline bonus.
"""

from .suite import Config, run

__all__ = ["Config", "run"]
