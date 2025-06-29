from importlib.util import find_spec

import os
from rics import configure_stuff

from id_translation import Translator
from id_translation.mapping.support import enable_verbose_debug_messages

assert find_spec("pandas") is None
assert find_spec("numpy") is None

configure_stuff(id_translation_level="DEBUG")

os.environ["DVDRENTAL_PASSWORD"] = "Sofia123!"
os.environ["DVDRENTAL_CONNECTION_STRING"] = "postgresql+pg8000://postgres:{password}@localhost:5002/sakila"
translator = Translator.load_persistent_instance(
    "/tmp/id-translation/missing-dependencies/",
    config_path="../../tests/dvdrental/translation.toml",
    extra_fetchers=["../../tests/dvdrental/sql-fetcher.toml"],
    max_age="5 sec",
)

ids = [313, 797, 12, 1]
names = ["customer_id", "film_id", "category_id", "staff_id"]
with enable_verbose_debug_messages():
    result = translator.translate(ids, names=names, max_fails=0)
print(result)
