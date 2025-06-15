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
from id_translation.mapping.support import enable_verbose_debug_messages

ROOT = Path(__file__).parent.parent.joinpath("tests/dvdrental/")
OUTPUT_DIR = Path(__file__).parent
RECORDS_FILE = OUTPUT_DIR / "documentation/dvdrental-records.json"
RST_FILE = OUTPUT_DIR / "documentation/translation-logging.rst"


class JsonLogRecorder(logging.Handler):
    ORIGIN = datetime.fromisoformat("2019-05-11T20:30:00").timestamp()
    WRITE_ISOLATED_KEY_EVENTS = False

    def __init__(self):
        super().__init__()
        self.key_events = []
        self.all_records = []
        self.start = datetime.now()

    def emit(self, record: logging.LogRecord) -> None:
        _, mid, right = record.pathname.partition("/id_translation/")
        record.pathname = "".join(("<site-packages>", mid, right))
        record.created = self.ORIGIN + (datetime.now() - self.start).total_seconds()

        self.all_records.append(record.__dict__)
        record_dict = record.__dict__

        event_key = record_dict.get("event_key")
        if event_key and record_dict.get("context", "customer") in ("customer", "category"):
            self.key_events.append(record_dict)

    def flush(self) -> None:
        if not self.all_records:
            return

        if self.WRITE_ISOLATED_KEY_EVENTS:
            root = OUTPUT_DIR / "key-events"
            root.mkdir()

            for i, record in enumerate(self.key_events):
                output_file = root / f"key-events/{i:02d}-{record['event_title']}.json"
                with output_file.open("w") as f:
                    json.dump(record, f, indent=2)

        root = OUTPUT_DIR / "documentation"
        records = sorted(self.all_records, key=lambda d: d["created"])
        with RECORDS_FILE.open("w") as f:
            json.dump(records, f, indent=2)

        root.joinpath("dvdrental-exit-message.txt").write_text(
            "\n  ".join(textwrap.wrap(self.key_events[-1]["message"], width=80))
        )
        print(f"Dumped {len(self.all_records)} records in '{root}'.")

        by_name = defaultdict(int)
        for record in self.all_records:
            by_name[record["name"]] += 1

        counts = pd.Series(by_name).sort_values(ascending=False).head(10).to_frame("#records").to_string()
        print(counts)
        print("=" * counts.index("\n"))

        self.all_records = []
        self.key_events = []


def main():
    recorder = JsonLogRecorder()
    logging.basicConfig(level=logging.DEBUG, handlers=[recorder, logging.StreamHandler()])
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

    with enable_verbose_debug_messages():
        translator.translate(df, copy=False)

    pd.testing.assert_frame_equal(df, expected)

    recorder.flush()

    handle_rst()


def handle_rst() -> None:
    start, stop = find_doc_lines()
    content = RST_FILE.read_text()

    for part in f":lines: {start}-{stop}", f":lineno-start: {stop}":
        if part in content:
            print(f"\033[92mOK:\033[0m {part=}")
        else:
            print(f"\033[31mMISSING:\033[0m {part=}")


def find_doc_lines() -> tuple[int, int]:
    lines = RECORDS_FILE.read_text().splitlines()
    line0 = '    "event_title": "MULTIFETCHER.FETCH.EXIT",'
    line1 = '    "event_title": "TRANSLATOR.TRANSLATE.EXIT",'

    start = lines.index(line0)
    stop = lines.index(line1)
    for i, line in enumerate(lines[start:stop]):
        if line == "  },":
            return start + i + 2, len(lines) - 1

    raise ValueError("not found")


if __name__ == "__main__":
    main()
