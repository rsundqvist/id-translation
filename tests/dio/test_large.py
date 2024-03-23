"""Test large dataset optimizations.

Currently, only Pandas has them.
"""

from typing import ClassVar
from uuid import UUID

import pandas as pd
import pytest
from id_translation import Translator


@pytest.mark.parametrize("kind", [pd.Series, pd.Index])
class TestPandas:
    numbers: ClassVar = {20: "twenty", 19: "nineteen", 5: "five", 11: "eleven"}

    @staticmethod
    def run(numbers, kind):
        fetcher_data = {"source": {"id": list(numbers.keys()), "name": list(numbers.values())}}
        translatable = kind(list(numbers) * 1000, name="source")
        translator = Translator(fetcher_data)  # type: ignore[var-annotated, arg-type]

        translator.translate(translatable)

    def test_int(self, kind):
        self.run(self.numbers, kind)

    def test_uuid(self, kind):
        self.run({UUID(int=idx): name for idx, name in self.numbers.items()}, kind)
