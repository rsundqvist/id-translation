"""Generate dvdrental logs.

To start the db, run:
    docker run -p 5002:5432 --rm rsundqvist/sakila-preload:postgres
"""

import json
import logging
import os
import textwrap
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
import sqlalchemy

from id_translation import Translator
from id_translation import logging as _logging

from id_translation._tasks import _base_task

ROOT = Path(__file__).parent.parent.joinpath("tests/dvdrental/")
OUTPUT_DIR = Path(__file__).parent
RECORDS_FILE = OUTPUT_DIR / "documentation/dvdrental-records.json"
INFO_FILE = OUTPUT_DIR / "documentation/dvdrental-info-messages.log"
RST_FILE = OUTPUT_DIR / "documentation/translation-logging.rst"

class Random:
    def __init__(self, _):
        pass

    def randint(self, _, __):
        return 2019_05_11

_base_task.Random = Random
_logging.ENABLE_VERBOSE_LOGGING = True
_logging.LOGGER.setLevel(logging.DEBUG)


class JsonLogRecorder(logging.Handler):
    ORIGIN = datetime.fromisoformat("2019-05-11T20:30:00").timestamp()

    def __init__(self):
        super().__init__()
        self.all_records = []
        self.start = datetime.now()

    def emit(self, record: logging.LogRecord) -> None:
        _, mid, right = record.pathname.partition("/id_translation/")
        record.pathname = "".join(("<site-packages>", mid, right))
        record.created = self.ORIGIN + (datetime.now() - self.start).total_seconds()

        record_dict = record.__dict__
        self.all_records.append(record_dict)

    def flush(self) -> None:
        if not self.all_records:
            return

        records = sorted(self.all_records, key=lambda d: d["created"])
        with RECORDS_FILE.open("w") as f:
            json.dump(records, f, indent=2)
        print(f"Dumped {len(self.all_records)} records in '{RECORDS_FILE}'.")

        info_rows = []
        for record in records:
            if record["levelno"] == logging.INFO:
                message = "[{name}]: {message}".format_map(record)
                raw_lines = message.splitlines()
                lines = []
                for line in raw_lines:
                    wrapped_line = textwrap.wrap(line, width=80, replace_whitespace=False, subsequent_indent="    ")
                    lines.extend(wrapped_line)
                message = "\n".join(lines)
                info_rows.append(message)

        INFO_FILE.write_text("\n\n".join(info_rows))
        print(f"Dumped {len(info_rows)} INFO rows in '{INFO_FILE}'.")

        by_name = defaultdict(int)
        for record in self.all_records:
            by_name[record["name"]] += 1

        counts = pd.Series(by_name).sort_values(ascending=False)  # .head(10)
        counts["total"] = counts.sum()
        counts = counts.to_frame("#records").to_string()
        print(counts)
        print("=" * counts.index("\n"))

        self.all_records = []


def main():
    recorder = JsonLogRecorder()
    gray = "\033[37m"
    blue = "\033[34m"
    reset = "\033[0m"
    logging.basicConfig(
        format=f"{gray}%(asctime)s.%(msecs)03d{reset} {blue}%(levelname)8s{reset} [{gray}%(name)s{reset}] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        level=logging.DEBUG,
        handlers=[recorder, (logging.StreamHandler())],
    )
    os.environ["DVDRENTAL_PASSWORD"] = "Sofia123!"
    os.environ["DVDRENTAL_CONNECTION_STRING"] = "postgresql+pg8000://postgres:{password}@localhost:5002/sakila"

    translator = Translator.from_config(
        ROOT / "translation.toml",
        extra_fetchers=[ROOT / "sql-fetcher.toml"],
    )
    expected = pd.read_csv(ROOT / "translated.csv", index_col=0, parse_dates=["rental_date", "return_date"])
    sql_fetcher = translator.fetcher.children[1]

    with sql_fetcher.engine.connect() as conn:
        records = list(conn.execute(sqlalchemy.text((ROOT / "docker/tests/query.sql").read_text())))
    df = pd.DataFrame.from_records(records, columns=expected.columns).loc[expected.index]

    # Context hides all fetcher init logs since we call MultiFetcher.children above.
    df = translator.translate(df)

    pd.testing.assert_frame_equal(df, expected)

    recorder.flush()

    handle_rst()


def handle_rst() -> None:
    start, stop = find_doc_lines()
    content = RST_FILE.read_text()

    for part in f":lines: {start}-{stop}", f":lineno-start: {start}":
        if part in content:
            print(f"\033[92mOK:\033[0m {part=}")
        else:
            print(f"\033[31mMISSING:\033[0m {part=}")


def find_doc_lines() -> tuple[int, int]:
    lines = RECORDS_FILE.read_text().splitlines()

    for r, line in enumerate(reversed(lines)):
        if line == "  },":
            return len(lines) - r + 1, len(lines) - 1

    raise ValueError("not found")


if __name__ == "__main__":
    main()
