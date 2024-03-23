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
        translatable = kind(list(numbers) * 1000, name="source")
        translator: Translator[str, str, int] = Translator({"source": numbers})

        translator.translate(translatable)

    def test_int(self, kind):
        self.run(self.numbers, kind)

    def test_uuid(self, kind):
        self.run({UUID(int=idx): name for idx, name in self.numbers.items()}, kind)
