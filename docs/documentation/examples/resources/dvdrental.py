"""Input for the Sakila DVD Rental Database example.

To install dependencies, run:
    python -m pip install --user --upgrade pandas rics id-translation sqlalchemy pg8000

To start the image, run:
    docker run -p 5002:5432 --rm rsundqvist/sakila-preload:postgres

This will launch a postgres instance with data already loaded. For more information, see:
    https://hub.docker.com/r/rsundqvist/sakila-preload.
    https://id-translation.readthedocs.io/en/stable/documentation/examples/dvdrental.html
"""
import os
import sys

import pandas
import rics
import sqlalchemy

from id_translation import Translator

rics.configure_stuff()

# Credentials
CONNECTION_STRING = "postgresql+pg8000://postgres:{password}@localhost:5002/sakila"
PASSWORD = "Sofia123!"

# Verification
try:
    url = CONNECTION_STRING.format(password=PASSWORD)
    sqlalchemy.create_engine(url).connect()
except Exception as exc:
    print(f"Failed to connect. Is the database running? Exception:\n{exc}")
    print("To start the database, run:\n    docker run -p 5002:5432 --rm rsundqvist/sakila-preload:postgres")
    sys.exit(1)


# Download data to translate
url = CONNECTION_STRING.format(password=PASSWORD)
with (
    open("query.sql") as query,
    sqlalchemy.create_engine(url).connect() as con,
):
    df = pandas.read_sql(query.read(), con)

sample = df.sample(10)
print(sample)

# Create a Translator
os.environ.update(
    DVDRENTAL_CONNECTION_STRING=CONNECTION_STRING,
    DVDRENTAL_PASSWORD=PASSWORD,
)
translator = Translator.from_config(
    "translation.toml",
    extra_fetchers=["sql-fetcher.toml"],
)
print(translator)

print(translator.map(df))

translator.translate(df, inplace=True)
print(df.loc[sample.index])
