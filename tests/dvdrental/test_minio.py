import logging
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from id_translation import Translator
from id_translation.toml import load_toml_file

from .conftest import LINUX_ONLY, check_minio_status

pytestmark = [
    LINUX_ONLY,
    pytest.mark.filterwarnings("ignore:.*socket.*:ResourceWarning"),  # Makes CI/CD flaky
]
CONFIG_FILE = Path(__file__).parent / "minio.toml"

# Emits non JSON-serializable log messages.
for name in "botocore", "s3fs", "fsspec":
    logging.getLogger(name).setLevel(logging.WARNING)


def test_pandas_fetcher(imdb_translator):
    # Doesn't actually belong here, but requires Docker. So this is convenient.
    check_minio_status(_storage_options()["client_kwargs"]["endpoint_url"])

    # with pytest.warns(DeprecationWarning, match="datetime.datetime.utcnow"):
    put_objects(imdb_translator.fetch().to_pandas())
    translator: Translator[str, str, int] = Translator.from_config(CONFIG_FILE)
    assert translator.placeholders == {
        "name_basics": ["id", "to", "name", "from"],
        "title_basics": ["from", "to", "name", "runtimeMinutes", "original_name", "id"],
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


def test_check_minio_status_reports_friendly_error_when_down():
    """Verifies the guard itself, without touching the real (running) minio container."""
    dead_endpoint = "http://localhost:1"  # Nothing listens here.
    with pytest.raises(
        RuntimeError,
        match=r"Unable to connect to database for dialect='minio'\. Start the databases"
        r" by running:\n    \./run-docker-dvdrental\.sh",
    ):
        check_minio_status(dead_endpoint)


def _storage_options() -> dict[str, Any]:
    config = load_toml_file(CONFIG_FILE)["fetching"]["PandasFetcher"]
    return config["read_function_kwargs"]["storage_options"]  # type: ignore[no-any-return]


def put_objects(sources: dict[str, pd.DataFrame]) -> None:
    config = load_toml_file(CONFIG_FILE)["fetching"]["PandasFetcher"]
    storage_options = _storage_options()
    read_path_format = config["read_path_format"]

    for source, df in sources.items():
        path = read_path_format.format(source)
        df.to_csv(path, index=False, storage_options=storage_options)
