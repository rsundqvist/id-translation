from typing import assert_type
from uuid import UUID

import numpy as np
import pandas as pd
import pytest

from id_translation import Translator
from id_translation.dio.exceptions import NotInplaceTranslatableError
from id_translation.dio.integration.pandas import PandasIO as _PandasIO
from id_translation.dio.integration.pandas import PandasT
from id_translation.offline import TranslationMap
from id_translation.offline.types import PlaceholderTranslations
from id_translation.types import IdTypes

PandasIO = _PandasIO[PandasT, str, str, int | str]
del _PandasIO
UUID_ID = UUID(fields=(1, 0, 0, 0, 0, 0))


def test_extract_float():
    series = pd.Series([1.0, float("nan"), 2.0, np.nan, np.inf, -np.inf, 3.0, 1, -1, 1.0], name="source")
    extracted = PandasIO[pd.Series]().extract(series, names=["source"])
    assert extracted == {"source": [-1, 1, 2, 3]}


class TestMissingAsNan:
    @classmethod
    def insert(
        cls,
        translatable: PandasT,
        tmap: TranslationMap[str, str, int | str],
        names: list[str],
        missing_as_nan: bool = True,
    ) -> None:
        io = PandasIO[PandasT](missing_as_nan=missing_as_nan)
        io.insert(translatable, names, tmap, copy=False)

    def test_series(self, tmap):
        series = pd.Series(["1", float("nan")])
        self.insert(series, tmap, names=["str_source"])
        assert series.to_list() == ["1:StrOne", np.nan]

    def test_frame(self, tmap):
        df = pd.Series(["1", float("nan")]).to_frame("str_source")
        self.insert(df, tmap, names=["str_source"])
        assert df["str_source"].to_list() == ["1:StrOne", np.nan]

    def test_single_repeated_name(self, tmap):
        series = pd.Series(["1", float("nan")])
        self.insert(series, tmap, names=["str_source", "str_source"])
        assert series.to_list() == ["1:StrOne", np.nan]

    def test_different_names(self, tmap):
        series = pd.Series(list("ab"))

        with pytest.raises(NotImplementedError, match=r"missing_as_nan=True.*names=\['a', 'b'\]"):
            self.insert(series, tmap, names=["a", "b"])

    @pytest.mark.parametrize(
        "missing_as_nan, expected",
        [
            (True, ["00000001:UuidOne", "00000001:UuidOne", np.nan, np.nan]),
            (False, ["00000001:UuidOne", "00000001:UuidOne", "<Failed: id=UUID>", "<Failed: id=str>"]),
        ],
    )
    def test_uuid_conversions(self, tmap, missing_as_nan, expected):
        data = [UUID_ID, str(UUID_ID), UUID(int=2), str(UUID(int=2))]
        df = pd.Series(data).to_frame("uuid_source")
        self.insert(df, tmap, names=df.columns, missing_as_nan=missing_as_nan)
        assert df["uuid_source"].to_list() == expected


class TestInplace:
    def test_index(self, tmap):
        index = pd.Index([])
        with pytest.raises(NotInplaceTranslatableError, match="Index"):
            PandasIO[pd.Index]().insert(index, names=[], tmap=tmap, copy=False)

    def test_series_int(self, tmap):
        source = "int_source"
        series = pd.Series([1], name=source)

        with pytest.raises(NotInplaceTranslatableError, match="Series"):
            PandasIO[pd.Series]().insert(series, names=[source], tmap=tmap, copy=False)

        assert series[0] == 1

    def test_series_str(self, tmap):
        source = "str_source"
        series = pd.Series(["1"], name=source)
        result = PandasIO[pd.Series]().insert(series, names=[source], tmap=tmap, copy=False)
        assert result is None
        assert series[0] == "1:StrOne"


@pytest.fixture
def tmap() -> TranslationMap[str, str, IdTypes]:
    int_source = PlaceholderTranslations.from_dict("int_source", {1: "IntOne"})
    str_source = PlaceholderTranslations.from_dict("str_source", {"1": "StrOne"})
    uuid_source = PlaceholderTranslations.from_dict("uuid_source", {UUID_ID: "UuidOne"})
    return TranslationMap(
        source_translations={
            int_source.source: int_source,
            str_source.source: str_source,
            uuid_source.source: uuid_source,
        },
        fmt="{id!s:.8}:{name}",
        enable_uuid_heuristics=True,
        default_fmt="<Failed: id={id.__class__.__name__}>",
    )


@pytest.mark.parametrize("cls", [pd.Series, pd.Index])
class TestMultipleNames:
    def test_extract(self, cls, data):
        translatable = cls(data.values())
        actual = PandasIO[pd.Series | pd.Index]().extract(translatable, names=[*data])
        assert actual == {"uuid_source": [UUID_ID], "int_source": [1], "str_source": ["1"]}

    def test_translate(self, cls, tmap, data):
        """Does not test extraction; tmap is preloaded with the required IDs."""

        translator = Translator[str, str, IdTypes](
            tmap,
            fmt=tmap.fmt,
            enable_uuid_heuristics=tmap.enable_uuid_heuristics,
        )
        translatable = cls(data.values())
        actual = translator.translate(translatable, names=[*data]).to_list()
        assert actual == ["00000001:UuidOne", "1:IntOne", "1:StrOne"]

    @pytest.fixture(scope="class")
    def data(self) -> dict[str, IdTypes]:
        return {"uuid_source": UUID_ID, "int_source": 1, "str_source": "1"}


@pytest.mark.parametrize(
    "level, reorder",
    [
        (1, False),
        (-1, False),
        (0, True),
        (-2, True),
        ("source", False),
        ("source", True),
    ],
)
def test_multiindex_columns(tmap, level, reorder):
    data = {
        ("known", "int_source"): [1, 1, 1],
        ("mixed", "int_source"): [1, 2, 3],
        ("known", "str_source"): ["1", "1", "1"],
        ("mixed", "str_source"): ["1", "2", "a"],
        ("known", "uuid_source"): [UUID_ID, str(UUID_ID), UUID_ID],
        ("mixed", "uuid_source"): [UUID_ID, str(UUID(int=2)), UUID(int=2)],
    }
    df = pd.DataFrame(data)
    df.columns.names = ["other", "source"]

    if reorder:
        df = df.reorder_levels(["source", "other"], axis=1)

    io = PandasIO[pd.DataFrame](level=level)

    actual_names = io.names(df)
    assert actual_names == ["int_source", "str_source", "uuid_source"]

    actual_ids = io.extract(df, names=actual_names)
    assert actual_ids == {
        "int_source": [1, 2, 3],
        "str_source": ["1", "2", "a"],
        "uuid_source": ["00000000-0000-0000-0000-000000000002", str(UUID_ID)],  # NOTE: Cast to str!
    }

    translator = Translator[str, str, IdTypes](
        tmap,
        fmt=tmap.fmt,
        default_fmt=tmap.default_fmt,
        enable_uuid_heuristics=tmap.enable_uuid_heuristics,
    )

    translator.translate(df, copy=False, io_kwargs={"level": level})

    if reorder:
        df = df.reorder_levels(["other", "source"], axis=1)

    assert df.to_dict(orient="list") == {
        ("known", "int_source"): ["1:IntOne", "1:IntOne", "1:IntOne"],
        ("known", "str_source"): ["1:StrOne", "1:StrOne", "1:StrOne"],
        ("known", "uuid_source"): ["00000001:UuidOne", "00000001:UuidOne", "00000001:UuidOne"],
        ("mixed", "int_source"): ["1:IntOne", "<Failed: id=int>", "<Failed: id=int>"],
        ("mixed", "str_source"): ["1:StrOne", "<Failed: id=str>", "<Failed: id=str>"],
        ("mixed", "uuid_source"): ["00000001:UuidOne", "<Failed: id=str>", "<Failed: id=UUID>"],
    }


@pytest.mark.parametrize(
    "level, reorder",
    [
        (0, True),
        (1, False),
        (-1, False),
    ],
)
def test_series_from_multiindex_columns_frame(tmap, level, reorder):
    data = {
        ("known", "int_source"): [1, 1, 1],
    }
    df = pd.DataFrame(data)
    if reorder:
        df = df.reorder_levels([1, 0], axis=1)
    series = df.iloc[:, 0]

    io = PandasIO[pd.Series](level=level)

    actual_names = io.names(series)
    assert actual_names == ["int_source"]

    actual_ids = io.extract(series, names=actual_names)
    assert actual_ids == {"int_source": [1]}

    translator = Translator[str, str, IdTypes](
        tmap,
        fmt=tmap.fmt,
        default_fmt=tmap.default_fmt,
        enable_uuid_heuristics=tmap.enable_uuid_heuristics,
    )

    actual = translator.translate(series, io_kwargs={"level": level})
    assert actual.to_list() == ["1:IntOne", "1:IntOne", "1:IntOne"]
    assert actual.name == series.name


@pytest.mark.parametrize("cls", [pd.Series, pd.DataFrame])
@pytest.mark.parametrize("level", [2, "2"], ids=lambda s: type(s).__name__)
def test_bad_level(level: str | int, cls: type[PandasT]) -> None:
    """Annotations are added in PandasIO.names() only."""

    translatable = pd.Series(name=("level-1", "level-0"))
    if cls is pd.DataFrame:
        translatable = translatable.to_frame()
    io = PandasIO[PandasT](level=level)

    with pytest.raises(Exception) as info:
        io.names(translatable)

    assert f"PandasIO.{level=}" in info.value.__notes__


@pytest.mark.filterwarnings("ignore::pandas.errors.Pandas4Warning")
class TestAsCategory:
    @pytest.mark.parametrize(
        "missing_as_nan, expected_values, expected_categories",
        [
            (True, ["1:StrOne", np.nan], {"1:StrOne"}),
            (False, ["1:StrOne", "<Failed: id=str>"], {"1:StrOne", "<Failed: id=str>"}),
        ],
    )
    def test_series_str_interaction(self, tmap, missing_as_nan, expected_values, expected_categories):
        series = pd.Series(["1", "a"], name="str_source")
        io = PandasIO[pd.Series](as_category=True, missing_as_nan=missing_as_nan)
        result = io.insert(series, names=["str_source"], tmap=tmap, copy=True)
        assert_type(result, pd.Series | None)  # remove the assertion below if this fails. And many other places!
        assert result is not None

        assert isinstance(result.dtype, pd.CategoricalDtype)
        assert result.to_list() == expected_values
        assert set(result.cat.categories) == expected_categories

    @pytest.mark.parametrize(
        "missing_as_nan, expected_values, expected_categories",
        [
            (True, ["00000001:UuidOne", "00000001:UuidOne", np.nan, np.nan], {"00000001:UuidOne"}),
            (
                False,
                ["00000001:UuidOne", "00000001:UuidOne", "<Failed: id=UUID>", "<Failed: id=str>"],
                {"<Failed: id=str>", "00000001:UuidOne", "<Failed: id=UUID>"},
            ),
        ],
    )
    def test_series_uuid_interaction(self, tmap, missing_as_nan, expected_values, expected_categories):
        series = pd.Series([UUID_ID, str(UUID_ID), UUID(int=2), str(UUID(int=2))], name="uuid_source")
        io = PandasIO[pd.Series](as_category=True, missing_as_nan=missing_as_nan)
        result = io.insert(series, names=["uuid_source"], tmap=tmap, copy=True)
        assert result is not None

        assert isinstance(result.dtype, pd.CategoricalDtype)
        assert result.to_list() == expected_values
        assert set(result.cat.categories) == expected_categories

    def test_default_missing_as_nan_true_when_as_category_true(self, tmap):
        series = pd.Series(["1", "a"], name="str_source")
        io = PandasIO[pd.Series](as_category=True)
        result = io.insert(series, names=["str_source"], tmap=tmap, copy=True)
        assert result is not None

        assert isinstance(result.dtype, pd.CategoricalDtype)
        assert result.to_list() == ["1:StrOne", np.nan]
        assert list(result.cat.categories) == ["1:StrOne"]

    def test_default_missing_as_nan_false_when_as_category_false(self, tmap):
        series = pd.Series(["1", "a"], name="str_source")
        io = PandasIO[pd.Series](as_category=False)
        result = io.insert(series, names=["str_source"], tmap=tmap, copy=True)
        assert result is not None

        # Not categorical when as_category is False
        assert not isinstance(result.dtype, pd.CategoricalDtype)
        assert result.to_list() == ["1:StrOne", "<Failed: id=str>"]
