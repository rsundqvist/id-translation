import logging
from datetime import datetime
import os
from pathlib import Path

import pandas as pd
from contextlib import redirect_stdout

import sqlalchemy

from id_translation.logging import enable_verbose_debug_messages
from id_translation._utils import debug_logging_formatter
from id_translation import Translator
from tempfile import TemporaryDirectory
import subprocess



class TempFormatter(debug_logging_formatter.DebugLoggingFormatter):
    ORIGIN = datetime.fromisoformat("2019-05-11T20:30:00").timestamp()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start = datetime.now()

    def formatMessage(self, record: logging.LogRecord) -> str:
        _, mid, right = record.pathname.partition("/id_translation/")
        record.pathname = "".join(("<site-packages>", mid, right))
        record.created = self.ORIGIN + (datetime.now() - self.start).total_seconds()
        return super().formatMessage(record)


debug_logging_formatter.DebugLoggingFormatter = TempFormatter
debug_logging_formatter.shuffle = lambda items: items.sort()
ROOT = Path(__file__).parent.parent.joinpath("tests/dvdrental/")


def main():
    enable_verbose_debug_messages(style="rainbow")

    os.environ["DVDRENTAL_PASSWORD"] = "Sofia123!"
    os.environ["DVDRENTAL_CONNECTION_STRING"] = "postgresql+pg8000://postgres:{password}@localhost:5002/sakila"

    translator = Translator.from_config(ROOT / "translation.toml", extra_fetchers=[ROOT / "sql-fetcher.toml"])

    translator.initialize_sources()

    expected = pd.read_csv(ROOT / "translated.csv", index_col=0, parse_dates=["rental_date", "return_date"])
    sql_fetcher = translator.fetcher.children[1]

    with sql_fetcher.engine.connect() as conn:
        records = list(conn.execute(sqlalchemy.text((ROOT / "docker/tests/query.sql").read_text())))
    df = pd.DataFrame.from_records(records, columns=expected.columns).loc[expected.index]

    df = translator.translate(df)

    pd.testing.assert_frame_equal(df, expected)


if __name__ == "__main__":
    out_path = Path(__file__).parent.joinpath("_static/logging-style-rainbow.html")

    with TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        with tmpdir.joinpath("logs.txt").open("w") as f, redirect_stdout(f):
            main()

        # sudo apt install colorized-logs
        # ansi2html --title='My title' --no-wrap --white < /tmp/logs.txt > logs.txt.html
        args = [
            "ansi2html",
            "--title=Verbose logging output",
            "--no-wrap",
            "--white",  # Dark made isn't supported (by me), so need for two versions.
        ]
        output = subprocess.check_output(args, input=tmpdir.joinpath("logs.txt").read_bytes())

    out_path.write_bytes(output)
    print(f"\033[92mUpdated: '{out_path}'\033[0m")
