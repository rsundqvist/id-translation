import logging
import os
from pathlib import Path

import pandas as pd

from id_translation import Translator
from id_translation.utils import load_toml_file

from .conftest import LINUX_ONLY

pytestmark = LINUX_ONLY
CONFIG_FILE = Path(__file__).parent / "minio.toml"

# Emits non JSON-serializable log messages.
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("s3fs").setLevel(logging.WARNING)
logging.getLogger("fsspec").setLevel(logging.WARNING)


def test_pandas_fetcher():
    put_objects()

    translator: Translator[str, str, int] = Translator.from_config(CONFIG_FILE)

    assert translator.placeholders == {
        "name_basics": ["nconst", "deathYear", "primaryName", "birthYear"],
        "title_basics": ["startYear", "endYear", "primaryTitle", "runtimeMinutes", "originalTitle", "tconst"],
    }

    assert translator.translate(
        {
            "name_basics": [1, 2],
            "title_basics": [25509, 35803],
        },
    ) == {
        "name_basics": ["1:Fred Astaire", "2:Lauren Bacall"],
        "title_basics": ["25509:Les Misérables", "35803:The German Weekly Review"],
    }


def put_objects():
    config = load_toml_file(CONFIG_FILE)["fetching"]["PandasFetcher"]

    storage_options = config["read_function_kwargs"]["storage_options"]
    read_path_format = config["read_path_format"]

    # pip install fsspec s3fs
    for file in Path(os.environ["TEST_ROOT"]).glob("imdb/*.json"):
        df = pd.read_json(file)
        df.to_csv(read_path_format.format(file.stem), index=False, storage_options=storage_options)

    return read_path_format
