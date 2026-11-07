from uuid import UUID

import pandas as pd
import pytest

from id_translation import Translator
from id_translation.fetching import PandasFetcher
from id_translation.fetching._pandas_fetcher import _SUFFIX_TO_READER
from id_translation.fetching.types import IdsToFetch
from id_translation.mapping import Mapper


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
        ("{}.parquet.csv", pd.read_csv),
        ("{}.csv.parquet", pd.read_parquet),
        ("{}.jsonl", _SUFFIX_TO_READER[".jsonl"][1]),
        ("{}.parquet", pd.read_parquet),
        ("{}.parquet.pq-old", pd.read_parquet),
        ("C:\\data\\{}.csv", pd.read_csv),
        ("/data/.parquet-cache/{}.orc", pd.read_orc),
        ("/data.csv/{}/table.json", pd.read_json),
        ("{}.arrow", pd.read_feather),
        ("{}.pq", pd.read_parquet),
        ("ds/{}.parquet/", pd.read_parquet),
        ("{}.orc", pd.read_orc),
        ("{}.xlsx", pd.read_excel),
        ("{}.xls", pd.read_excel),
        ("{}.ods", pd.read_excel),
        ("https://host/data/{}.csv", pd.read_csv),
        ("https://host/data/{}.csv?v=1.csv", pd.read_csv),  # 2.0 also derives read_csv: no warning.
        ("https://host/get?file={}.csv", pd.read_csv),  # 1.4.2 and 2.0 agree: no warning.
    ],
)
def test_derive_read_function(path, expected):
    assert PandasFetcher(read_path_format=path)._read is expected


@pytest.mark.parametrize("suffix", [".jsonl", ".ndjson"])
def test_derive_json_lines(tmp_path, suffix):
    pd.DataFrame({"id": [1, 2], "name": ["a", "b"]}).to_json(tmp_path / f"source{suffix}", orient="records", lines=True)
    fetcher: PandasFetcher[int] = PandasFetcher(read_path_format=str(tmp_path / f"{{}}{suffix}"))
    assert fetcher.find_sources() == {"source": str(tmp_path / f"source{suffix}")}
    assert fetcher.read(fetcher.format_source("source"))["name"].tolist() == ["a", "b"]


@pytest.mark.parametrize("suffix", _SUFFIX_TO_READER)
def test_docstring_lists_derivable_suffix(suffix):
    assert f"``{suffix}``" in (PandasFetcher.__doc__ or "")


def test_derive_unknown_suffix():
    with pytest.raises(ValueError, match="Cannot derive"):
        PandasFetcher(read_path_format="{}.unknown")


@pytest.mark.parametrize("return_all", [False, True])
def test_return_all(tmp_path, return_all):
    pd.DataFrame({"code": ["US", "SE", "NO"], "name": ["USA", "Sweden", "Norway"], "pop": [335, 10, 5]}).to_csv(
        tmp_path / "countries.csv", index=False
    )
    fetcher: PandasFetcher[str] = PandasFetcher(
        read_path_format=str(tmp_path / "{}.csv"), return_all=return_all, mapper=Mapper(overrides={"id": "code"})
    )

    actual = fetcher.fetch([IdsToFetch("countries", {"US", "SE"})], placeholders=("name",))["countries"]

    if return_all:
        assert actual.placeholders == ("id", "name", "pop")
        assert len(actual.records) == 3
    else:
        assert actual.placeholders == ("id", "name")
        assert sorted(map(tuple, actual.records)) == [("SE", "Sweden"), ("US", "USA")]


def test_return_all_defaults_to_true():
    assert PandasFetcher().return_all


def test_uuid_heuristics_with_ids_that_are_not_all_uuid_like(tmp_path):
    u = str(UUID(int=7))
    pd.DataFrame({"id": [u, "x"], "name": ["uuid", "ex"]}).to_csv(tmp_path / "s.csv", index=False)
    fetcher: PandasFetcher[str] = PandasFetcher(read_path_format=str(tmp_path / "{}.csv"), return_all=False)
    translator: Translator[str, str, str] = Translator(fetcher, fmt="{name}", enable_uuid_heuristics=True)
    assert translator.translate([u, "x"], names="s") == ["uuid", "ex"]


@pytest.mark.parametrize(
    "path, expected",
    [("data/export.parquet_{}", pd.read_parquet), ("{}.csv_old", pd.read_csv)],
)
def test_derive_from_a_suffix_outside_the_file_name_warns(path, expected):
    with pytest.warns(FutureWarning, match="outside the file name suffixes"):
        assert PandasFetcher(read_path_format=path)._read is expected


@pytest.mark.parametrize(
    "path, expected",
    [
        ("https://host/data/{}.csv?raw=true#top", pd.read_csv),  # 2.0 raises.
        ("https://host/data/{}.csv?name=export.parquet", pd.read_csv),  # 2.0 reads parquet.
        ("https://host/data/{}.parquet#v.csv", pd.read_parquet),  # 2.0 reads CSV.
    ],
)
def test_derive_from_a_url_query_or_fragment_warns(path, expected):
    with pytest.warns(FutureWarning, match="ignoring its query and fragment"):
        assert PandasFetcher(read_path_format=path)._read is expected


def test_derive_from_a_url_query_outside_the_path_warns_with_what_2_0_derives():
    with pytest.warns(FutureWarning, match=r"2\.0\.0` derives read_function='pandas\.read_parquet' instead"):
        assert PandasFetcher(read_path_format="https://host/{}?a=.csv&b=.parquet")._read is pd.read_csv
