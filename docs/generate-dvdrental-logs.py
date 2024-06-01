"""Generate dvdrental logs.

To start the db, run:
    docker run -p 5002:5432 --rm rsundqvist/sakila-preload:postgres
"""

import json
import logging
import os
import textwrap
from datetime import datetime
from pathlib import Path

import pandas as pd
import sqlalchemy

from id_translation import Translator
from id_translation.mapping.support import enable_verbose_debug_messages

OUTPUT_DIR = Path(__file__).parent
ROOT = Path(__file__).parent.parent.joinpath("tests/dvdrental/")


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
        if self.WRITE_ISOLATED_KEY_EVENTS:
            root = OUTPUT_DIR / "key-events"
            root.mkdir()

            for i, record in enumerate(self.key_events):
                output_file = root / f"key-events/{i:02d}-{record['event_title']}.json"
                with output_file.open("w") as f:
                    json.dump(record, f, indent=2)

        root = OUTPUT_DIR / "documentation"
        records = sorted(self.all_records, key=lambda d: d["created"])
        with root.joinpath("dvdrental-records.json").open("w") as f:
            json.dump(records, f, indent=2)

        root.joinpath("dvdrental-exit-message.txt").write_text(
            "\n  ".join(textwrap.wrap(self.key_events[-1]["message"], width=80))
        )
        print(f"Dumped {len(self.all_records)} records in '{root}'.")


def main():
    logging.basicConfig(level=logging.DEBUG, handlers=[JsonLogRecorder(), logging.StreamHandler()])
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


if __name__ == "__main__":
    main()
