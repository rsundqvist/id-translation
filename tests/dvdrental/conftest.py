import os
from pathlib import Path

import sqlalchemy
import yaml  # type: ignore

from id_translation import Translator

ROOT = Path(__file__).parent
DOCKER_ROOT = ROOT.joinpath("docker")
CREDENTIALS = yaml.safe_load(DOCKER_ROOT.joinpath("credentials.yml").read_text())["dialects"]
for k, v in dict(
    mysql="pymysql",
    postgresql="pg8000",
    mssql="pymssql",
).items():
    CREDENTIALS[k]["driver"] = v

QUERY = DOCKER_ROOT.joinpath("tests/query.sql").read_text()


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


def get_translator(dialect: str) -> Translator[str, str, int]:
    os.environ["DVDRENTAL_PASSWORD"] = "Sofia123!"
    os.environ["DVDRENTAL_CONNECTION_STRING"] = get_connection_string(dialect, with_password=False)
    extra_fetchers = [ROOT.joinpath("sql-fetcher.toml")]
    config = ROOT.joinpath("translation.toml")
    return Translator.from_config(config, extra_fetchers)
