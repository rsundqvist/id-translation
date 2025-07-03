from importlib.util import find_spec

import os
import pandas as pd
from rics import configure_stuff

from id_translation import Translator
from id_translation.logging import enable_verbose_debug_messages

assert find_spec("sqlalchemy") is None

configure_stuff(id_translation_level="DEBUG")

os.environ["TEST_ROOT"] = "../../tests/"

translator = Translator.load_persistent_instance(
    "/tmp/id-translation/missing-dependencies/",
    config_path="../../tests/config.imdb.toml",
    max_age="5 sec",
)

df = pd.DataFrame([[1, 25509]], columns=["nconst", "title_basics"])

with enable_verbose_debug_messages():
    result = translator.translate(df, max_fails=0)
print(result)
