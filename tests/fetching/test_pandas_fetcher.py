from typing import Union
from uuid import UUID

import pandas as pd
import pytest

from id_translation import Translator
from id_translation.fetching import PandasFetcher


@pytest.mark.parametrize("kind", [str, UUID])
class TestUuids:
    def test_csv(self, tmp_path, kind):
        self.make_frame(kind).to_csv(tmp_path / "source.suffix")
        self.run(pd.read_csv, tmp_path)

    def test_pickle(self, tmp_path, kind):
        self.make_frame(kind).to_pickle(tmp_path / "source.suffix")
        self.run(pd.read_pickle, tmp_path)

    def test_json(self, tmp_path, kind):
        self.make_frame(kind).to_json(tmp_path / "source.suffix", default_handler=_uuid_as_string)
        self.run(pd.read_json, tmp_path)

    @classmethod
    def run(cls, read_function, tmp_path):
        translator: Translator[str, str, Union[str, UUID]] = Translator(
            PandasFetcher(read_function, read_path_format=str(tmp_path / "{}.suffix")),
            fmt="{id!s:.8}:{name}",
            enable_uuid_heuristics=True,
        )
        actual = translator.translate([cls.uuid, UUID(cls.uuid)], names="source")
        assert actual == ["20190511:Saturday", "20190511:Saturday"]

    uuid = "20190511-0000-0000-0000-000000000000"

    @classmethod
    def make_frame(cls, kind):
        return pd.DataFrame({"id": [kind(cls.uuid)], "name": ["Saturday"]})


def _uuid_as_string(val):
    if isinstance(val, UUID):
        return str(val)
    return val
