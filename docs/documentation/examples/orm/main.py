"""A naive ORM fetching implementation.

Downloaded from:
    https://id-translation.readthedocs.io/en/stable/documentation/examples/orm/orm.html

This module is a simple usage example for the ``MyOrmFetcher`` class.
"""

from dvdrental_models import SakilaBase
from id_translation import Translator
from id_translation.logging import enable_verbose_debug_messages
from id_translation.mapping import HeuristicScore, Mapper
from orm_fetcher import MyOrmFetcher
from sqlalchemy import create_engine

enable_verbose_debug_messages(style="rainbow")

orm_fetcher = MyOrmFetcher(
    engine=create_engine("postgresql://postgres:Sofia123!@localhost:5002/sakila"),
    models=MyOrmFetcher.from_base_model(SakilaBase),
    preload_attributes=True,
    mapper=Mapper(
        score_function=HeuristicScore("equality", heuristics=["smurf_columns"]),
        overrides={"stuff": "inventory"},
    ),
)
translator = Translator(orm_fetcher)
print(translator.fetcher)

print("Rental=[20, 19]:")
for result in translator.translate(
    [20, 19],
    names="Rental",
    fmt=(
        "{staff.first_name} rented "
        "{inventory.film.title} ({stuff.film.release_year})"
        " to {customer.first_name} on {rental_date:%Y-%m-%d}."
    ),
):
    print("*", result)

print("Actor=[5, 11]:")
for result in translator.translate(
    [5, 11],
    names="Actor",
    fmt="{actor_id}: {first_name} {last_name} (first film={films[0].title!r})",
):
    print("*", result)
