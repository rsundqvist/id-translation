from pathlib import Path

import yaml as _yaml

_PATH = Path("tests/dvdrental/docker/credentials.yml")

with _PATH.open() as f:
    _RAW = _yaml.safe_load(f)["dialects"]

_DRIVERS = {
    "mysql": "pymysql",
    "postgresql": "pg8000",
    "mssql": "pymssql",
}
_TEMPLATE = "{dialect}+{driver}://{user}:{password}@localhost:{port}/{database}"

for dialect, args in _RAW.items():
    connection_string = _TEMPLATE.format(driver=_DRIVERS[dialect], dialect=dialect, **args)
    print(dialect.upper(), "=", '"' + connection_string + '"')

MYSQL = "mysql+pymysql://root:Sofia123!@localhost:5001/sakila"
POSTGRESQL = "postgresql+pg8000://postgres:Sofia123!@localhost:5002/sakila"
MSSQL = "mssql+pymssql://sa:Sofia123!@localhost:5003/sakila"
