from pathlib import Path
from uuid import UUID

import pandas as pd
import pytest

from id_translation import Translator
from id_translation.fetching import PandasFetcher
from id_translation.fetching._pandas_fetcher import _SUFFIX_TO_READER
from id_translation.fetching.exceptions import UnknownIdPlaceholderError
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


def test_uuid_heuristics_with_ids_that_are_not_all_uuid_like(tmp_path):
    u = str(UUID(int=7))
    pd.DataFrame({"id": [u, "x"], "name": ["uuid", "ex"]}).to_csv(tmp_path / "s.csv", index=False)
    fetcher: PandasFetcher[str] = PandasFetcher(read_path_format=str(tmp_path / "{}.csv"))
    translator: Translator[str, str, str] = Translator(fetcher, fmt="{name}", enable_uuid_heuristics=True)
    assert translator.translate([u, "x"], names="s") == ["uuid", "ex"]


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


@pytest.mark.parametrize(
    "read_path_format",
    [
        pd.read_csv,
        "read_csv",
        "pandas.read_csv",
        "pandas.io.json.read_json",
        "{}.unknown",
        "data/countries.tsv",
        "data/countries.csv",
        "data/*.csv",
        lambda source: f"{source}.tsv",
    ],
    ids=[
        "1.x-function",
        "1.x-name",
        "1.x-full-name",
        "1.x-full-name-with-suffix",
        "unknown-suffix",
        "fixed-path",
        "fixed-path-with-suffix",
        "fixed-glob",
        "format-function",
    ],
)
def test_underivable_read_function_hints_at_keyword(read_path_format):
    with pytest.raises(ValueError, match="Cannot derive") as exc_info:
        PandasFetcher(read_path_format)
    assert "Set `read_function`" in "".join(exc_info.value.__notes__)


def test_fixed_path_with_own_find_sources(tmp_path):
    """Only the default discovery needs a placeholder; the reader is still derived from the suffix."""
    path = tmp_path / "people.csv"
    path.write_text("id,name\n1,Ada\n")

    class FixedPath(PandasFetcher[int]):
        def find_sources(self, task_id: int | None = None) -> dict[str, str]:  # noqa: ARG002
            return {"people": str(path)}

    fetcher = FixedPath(str(path))
    assert fetcher.fetch_all(("id", "name"))["people"].records == [[1, "Ada"]]


def test_own_format_source_picks_the_reader_from_read_path_format(tmp_path):
    """The default discovery globs what format_source('*') returns; read_path_format only picks the reader."""
    (tmp_path / "people.csv").write_text("id,name\n1,Ada\n")

    class OwnFormat(PandasFetcher[int]):
        def format_source(self, source: str) -> str:
            return str(tmp_path / f"{source}.csv")

    fetcher = OwnFormat("any.csv")
    assert fetcher.fetch_all(("id", "name"))["people"].records == [[1, "Ada"]]


@pytest.mark.parametrize("path", ["people.csv", "*.csv"], ids=["fixed-path", "fixed-glob"])
def test_own_format_source_that_ignores_the_source_raises_at_discovery(tmp_path, path):
    class OwnFormat(PandasFetcher[int]):
        def format_source(self, source: str) -> str:  # noqa: ARG002
            return str(tmp_path / path)

    fetcher = OwnFormat("any.csv")
    with pytest.raises(ValueError, match=r"format_source\('\*'\) returned .*, which does not glob by source name"):
        fetcher.initialize_sources()


def test_fixed_path_with_read_function_raises():
    """Without a placeholder, the default discovery cannot find sources, whatever reads them."""
    with pytest.raises(ValueError, match=r"^Cannot use read_path_format='people\.csv'; it has no") as exc_info:
        PandasFetcher("people.csv", read_function="read_csv")
    assert exc_info.value.__notes__ == ["Hint: Put `{}` where the source name goes, e.g. `'data/{}.csv'`."]


@pytest.mark.parametrize(
    "read_path_format",
    ["data/{source}.csv", "data/{}/{}.csv", "data/{.csv", "data/{.csv}", "data/{0[x]}.csv"],
)
def test_bad_format_raises_at_construction(read_path_format):
    with pytest.raises(ValueError, match="it is formatted with the source name alone"):
        PandasFetcher(read_path_format)


def test_path_object_has_no_read_function_hint():
    """A `Path` is not a supported format at all; passing `read_function` would not help."""
    with pytest.raises(ValueError, match="Cannot derive") as exc_info:
        PandasFetcher(Path("{}.csv"))  # type: ignore[arg-type]
    assert not getattr(exc_info.value, "__notes__", [])


@pytest.mark.parametrize("return_all", [False, True])
def test_return_all(tmp_path, return_all):
    pd.DataFrame({"code": ["US", "SE", "NO"], "name": ["USA", "Sweden", "Norway"], "pop": [335, 10, 5]}).to_csv(
        tmp_path / "countries.csv", index=False
    )
    fetcher: PandasFetcher[str] = PandasFetcher(
        str(tmp_path / "{}.csv"), return_all=return_all, mapper=Mapper(overrides={"id": "code"})
    )

    actual = fetcher.fetch([IdsToFetch("countries", {"US", "SE"})], placeholders=("name",))["countries"]

    if return_all:
        assert actual.placeholders == ("id", "name", "pop")
        assert len(actual.records) == 3
    else:
        assert actual.placeholders == ("id", "name")
        assert sorted(map(tuple, actual.records)) == [("SE", "Sweden"), ("US", "USA")]


def test_file_without_id_column(tmp_path):
    pd.DataFrame({"id": [1], "name": ["Fred"]}).to_csv(tmp_path / "people.csv", index=False)
    pd.DataFrame({"when": ["2026"], "note": ["x"]}).to_csv(tmp_path / "notes.csv", index=False)
    fetcher: PandasFetcher[int] = PandasFetcher(f"{tmp_path}/{{}}.csv")

    with pytest.raises(UnknownIdPlaceholderError) as exc_info:
        fetcher.initialize_sources()
    assert exc_info.value.source == "notes"
    hint = f"Hint: If {f'{tmp_path}/notes.csv'!r} is not a source, change read_path_format="  # As formatted.
    assert any(note.startswith(hint) for note in exc_info.value.__notes__)
