from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def data() -> dict[str, pd.DataFrame]:
    return {
        "animals": pd.DataFrame(
            {"id": [0, 1, 2], "name": ["Tarzan", "Morris", "Simba"], "is_nice": [False, True, True]}
        ),
        "humans": pd.DataFrame({"id": [1991, 1999], "name": ["Richard", "Sofia"], "gender": ["Male", "Female"]}),
        "big_table": pd.DataFrame({"id": range(100)}),
        "huge_table": pd.DataFrame({"id": range(1000)}),
    }


@pytest.fixture(scope="module")
def windows_hack_temp_dir():
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        yield Path(tmpdir)
