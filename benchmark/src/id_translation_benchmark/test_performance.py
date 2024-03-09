from uuid import UUID

import pandas as pd
import pytest

from id_translation_benchmark.support import run_benchmark
from id_translation_benchmark.types import IdFactories


def uuid_string(i: int) -> str:
    return str(UUID(int=i))


pytestmark = pytest.mark.parametrize("id_type", IdFactories)


# @pytest.mark.skip
class Benchmark:
    """
    pip install pytest-benchmark[histogram]
    pytest tests/ --benchmark-only --benchmark-histogram=.benchmarks/plots/histogram --benchmark-autosave \
        --benchmark-compare
    """

    @pytest.mark.parametrize("translatable_type", [pd.Series, pd.Index])
    def test_pandas(self, id_type, translatable_type, count, benchmark):
        run_benchmark(id_type, translatable_type, count, benchmark)

    @pytest.mark.parametrize("translatable_type", [list, dict, tuple])
    def test_builtins(self, id_type, translatable_type, count, benchmark):
        run_benchmark(id_type, translatable_type, count, benchmark)


@pytest.mark.parametrize("count", [1, 5, 25, 500, 2500, 25_000])
class TestBenchmarks(Benchmark):
    pass


@pytest.mark.parametrize(
    "count",
    [
        5_000_000,
        25_000_000,
        250_000_000,
    ],
)
class TestSlowBenchmarks(Benchmark):
    pass
