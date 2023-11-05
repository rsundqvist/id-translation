import os
from pathlib import Path
from typing import List, Tuple

import pandas as pd
import sqlalchemy
import yaml  # type: ignore

ROOT = Path(__file__).parent
DOCKER_ROOT = ROOT.joinpath("docker")
CREDENTIALS = yaml.safe_load(DOCKER_ROOT.joinpath("credentials.yml").read_text())["dialects"]
for dialect, driver in dict(
    mysql="pymysql",
    postgresql="pg8000",
    mssql="pymssql",
).items():
    CREDENTIALS[dialect]["driver"] = driver

QUERY = DOCKER_ROOT.joinpath("tests/query.sql").read_text()

DIALECTS = [
    "mysql",
    "postgresql",
    "mssql",  # Quite slow, mostly since the (pyre-python) driver used doesn't support fast_executemany
]


def get_df(dialect: str) -> pd.DataFrame:
    with sqlalchemy.create_engine(get_connection_string(dialect)).connect() as conn:
        cursor = conn.execute(sqlalchemy.text(QUERY))
        return pd.DataFrame.from_records(list(cursor), columns=cursor.keys())


def check_status(dialect: str) -> None:
    engine = sqlalchemy.create_engine(get_connection_string(dialect))

    try:
        with engine.connect() as conn:
            count = next(conn.execute(sqlalchemy.text("SELECT count(*) FROM store")))
    except Exception:  # noqa: B902
        msg = (
            f"Unable to connect to database for {dialect=}. Start the databases"
            " by running:\n    ./run-docker-dvdrental.sh"
        )
        raise RuntimeError(msg)

    assert count[0] == 2, f"Expected 2 stores, but got {count}."


def get_connection_string(dialect: str, with_password: bool = True) -> str:
    kwargs = CREDENTIALS[dialect]
    ans = "{dialect}+{driver}://{user}:{{password}}@localhost:{port}/sakila".format(dialect=dialect, **kwargs)
    return ans.format(password=kwargs["password"]) if with_password else ans


def setup_for_dialect(dialect: str) -> Tuple[Path, List[Path]]:
    os.environ["DVDRENTAL_PASSWORD"] = "Sofia123!"
    os.environ["DVDRENTAL_CONNECTION_STRING"] = get_connection_string(dialect, with_password=False)
    return (
        ROOT.joinpath("translation.toml"),
        [ROOT.joinpath("sql-fetcher.toml")],
    )
