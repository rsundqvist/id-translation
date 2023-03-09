from pathlib import Path
from shutil import rmtree
from tempfile import TemporaryDirectory
from typing import Dict

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def data() -> Dict[str, pd.DataFrame]:
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
    with TemporaryDirectory() as tmpdir:  # 3.10; ignore_cleanup_errors=True
        tmp_root = Path(tmpdir).parent
    ans = tmp_root.joinpath("windows-resistant-tempdir")
    yield ans
    rmtree(ans, ignore_errors=True)
