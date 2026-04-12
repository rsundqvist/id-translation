from engine import ENGINE
from models import Child, Parent
from orm_fetcher import OrmFetcher
from sqlalchemy.orm import Session

from id_translation import Translator
from id_translation.fetching import SqlFetcher

sql_fetcher = SqlFetcher(ENGINE.url.render_as_string(hide_password=False))
orm_fetcher = OrmFetcher(
    ENGINE,
    models=[
        Parent,
        # Child,
    ],
)
translator = Translator(orm_fetcher)

print(translator.placeholders)

data = [1, 1, 2]

translated_data = translator.translate(
    data,
    names=["Parent"],
    fmt="{id}:{name} ({child.id}:{child.name})",
)
print(translated_data)

translated_data = translator.translate(
    data,
    names=["Parent"],
    fmt="{id}:{name} ({child.id}:{child.name} - {child.parent.name})",
)
print(translated_data)
