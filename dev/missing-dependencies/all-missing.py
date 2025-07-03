from importlib.util import find_spec

from id_translation import Translator
from id_translation.mapping import Mapper
from rics import configure_stuff
from id_translation.logging import enable_verbose_debug_messages

assert find_spec("pandas") is None
assert find_spec("numpy") is None
assert find_spec("sqlalchemy") is None

configure_stuff(id_translation_level="DEBUG")

mapper = Mapper(overrides={"name": "source"})


translator = Translator.load_persistent_instance(
    "/tmp/id-translation/missing-dependencies/",
    config_path="../../tests/transform/main.toml",
    extra_fetchers=["../../tests/transform/fetcher-only.toml"],
    max_age="5 sec",
)
with enable_verbose_debug_messages():
    result = translator.translate(2021, "guests", max_fails=0)
assert result == "What's up, Morris?"

translator = Translator(fetcher={"source": {1: "name"}}, mapper=mapper)
with enable_verbose_debug_messages():
    result = translator.translate(1, "name", max_fails=0)

assert result == "1:name"
