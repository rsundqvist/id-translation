from uuid import UUID

import pandas as pd
import pytest

from id_translation import Translator
from id_translation.fetching import PandasFetcher
from id_translation.fetching._pandas_fetcher import _SUFFIX_TO_READER


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
        translator: Translator[str, str, str | UUID] = Translator(
            PandasFetcher(str(tmp_path / "{}.suffix"), read_function=read_function),
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


@pytest.mark.parametrize(
    "path, expected",
    [
        ("{}.csv.zip", pd.read_csv),
        ("/data/.parquet-cache/{}.orc", pd.read_orc),
        ("/data.csv/{}/table.json", pd.read_json),
        ("{}.arrow", pd.read_feather),
        ("{}.pq", pd.read_parquet),
        ("ds/{}.parquet/", pd.read_parquet),
        ("{}.orc", pd.read_orc),
        ("{}.xlsx", pd.read_excel),
        ("{}.xls", pd.read_excel),
        ("{}.ods", pd.read_excel),
    ],
)
def test_derive_read_function(path, expected):
    assert PandasFetcher(path)._read is expected


@pytest.mark.parametrize("suffix", [".jsonl", ".ndjson"])
def test_derive_json_lines(tmp_path, suffix):
    pd.DataFrame({"id": [1, 2], "name": ["a", "b"]}).to_json(tmp_path / f"source{suffix}", orient="records", lines=True)
    fetcher: PandasFetcher[int] = PandasFetcher(str(tmp_path / f"{{}}{suffix}"))
    assert fetcher.find_sources() == {"source": str(tmp_path / f"source{suffix}")}
    assert fetcher.read(fetcher.format_source("source"))["name"].tolist() == ["a", "b"]


@pytest.mark.parametrize(
    "path, expected",
    [
        ("{}.json", "read_function=pandas.read_json,"),
        ("{}.jsonl", "read_function=pandas.read_json(lines=True),"),
    ],
)
def test_repr_names_derived_read_function(path, expected):
    assert expected in repr(PandasFetcher(path))


@pytest.mark.parametrize("suffix", _SUFFIX_TO_READER)
def test_docstring_lists_derivable_suffix(suffix):
    assert f"``{suffix}``" in (PandasFetcher.__doc__ or "")


def test_derive_unknown_suffix():
    with pytest.raises(ValueError, match="Cannot derive"):
        PandasFetcher("{}.unknown")
