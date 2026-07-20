from typing import assert_type
from uuid import UUID

import numpy as np
import pandas as pd
import pytest

from id_translation import Translator
from id_translation.dio.exceptions import NotInplaceTranslatableError
from id_translation.dio.integration.pandas import PandasIO as _PandasIO
from id_translation.dio.integration.pandas import PandasT, _is_missing, _sorted_ids
from id_translation.offline import TranslationMap
from id_translation.offline.types import PlaceholderTranslations
from id_translation.transform.types import Transformer
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


@pytest.mark.filterwarnings("ignore::pandas.errors.Pandas4Warning")
class TestOrdered:
    """IDs are chosen so that ID order and translated-name order disagree."""

    @pytest.mark.parametrize(
        "ordered, expected_categories, expected_ordered",
        [
            ("name", ["a", "b", "c"], True),
            ("id", ["c", "a", "b"], True),
            (False, ["a", "b", "c"], False),
        ],
    )
    def test_categories(self, ordered_tmap, ordered, expected_categories, expected_ordered):
        series = pd.Series([1, 2, 10], name="s")
        io = PandasIO[pd.Series](as_category=True, ordered=ordered)
        result = io.insert(series, names=["s"], tmap=ordered_tmap, copy=True)
        assert result is not None

        assert result.cat.categories.to_list() == expected_categories
        assert result.dtype.ordered is expected_ordered
        assert result.to_list() == ["c", "a", "b"]

    def test_default_is_name(self, ordered_tmap):
        series = pd.Series([1, 2, 10], name="s")
        io = PandasIO[pd.Series](as_category=True)
        result = io.insert(series, names=["s"], tmap=ordered_tmap, copy=True)
        assert result is not None

        assert result.cat.categories.to_list() == ["a", "b", "c"]
        assert result.dtype.ordered is True

    def test_id_order_keeps_placeholders(self, ordered_tmap):
        series = pd.Series([1, 2, 10, -1], name="s")
        io = PandasIO[pd.Series](as_category=True, ordered="id", missing_as_nan=False)
        result = io.insert(series, names=["s"], tmap=ordered_tmap, copy=True)
        assert result is not None

        # The unknown ID sorts by its own ID, ahead of the real translations.
        assert result.cat.categories.to_list() == ["<Failed: id=-1>", "c", "a", "b"]

    def test_id_order_dedupes_shared_translations(self, ordered_tmap):
        """Categories must be unique even when several IDs translate to the same name."""
        series = pd.Series([1, 2, 3, 10], name="s")
        io = PandasIO[pd.Series](as_category=True, ordered="id")
        result = io.insert(series, names=["s"], tmap=ordered_tmap, copy=True)
        assert result is not None

        assert result.cat.categories.to_list() == ["c", "a", "b"]
        assert result.to_list() == ["c", "a", "a", "b"]

    def test_id_order_sorts_comparable_mixed_types_by_value(self, ordered_tmap):
        """Known IDs are `int` (from `real`), the unknown one `float` (from `extra`); they must sort by value."""
        series = pd.Series([1.0, 5.0, 10.0], name="s")
        io = PandasIO[pd.Series](as_category=True, ordered="id", missing_as_nan=False)
        result = io.insert(series, names=["s"], tmap=ordered_tmap, copy=True)
        assert result is not None

        # Grouping by type name would put the lone float ahead of every int.
        assert result.cat.categories.to_list() == ["c", "a", "<Failed: id=5.0>", "b"]

    @pytest.mark.parametrize("ordered", [True, "nope", None])
    def test_bad_value(self, ordered):
        with pytest.raises(ValueError, match="expected 'name', 'id' or False"):
            PandasIO[pd.Series](as_category=True, ordered=ordered)

    @pytest.fixture(scope="class")
    def ordered_tmap(self) -> TranslationMap[str, str, IdTypes]:
        # ID 3 shares a translation with ID 2.
        translations = PlaceholderTranslations.from_dict("s", {1: "c", 2: "a", 3: "a", 10: "b"})
        return TranslationMap(
            source_translations={translations.source: translations},
            fmt="{name}",
            default_fmt="<Failed: id={id}>",
        )


class TestUuidJoin:
    """UUID heuristics key the backing dict by UUID objects; the join must normalize to match."""

    UUIDS = ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "11111111-2222-3333-4444-555555555555"]

    def translator(self, ids):
        data = {"src": {"id": ids, "name": ["first", "second"]}}
        return Translator(data, fmt="{id}:{name}", enable_uuid_heuristics=True)

    @pytest.mark.parametrize("source_kind", [str, str.upper, UUID])
    @pytest.mark.parametrize("lookup_kind", [str, str.upper, UUID])
    def test_join_hits_for_all_representations(self, source_kind, lookup_kind):
        source_ids = [source_kind(u) for u in self.UUIDS]
        translator = self.translator(source_ids)
        series = pd.Series([lookup_kind(u) for u in self.UUIDS], name="src")

        actual = translator.translate(series)

        # Heuristics normalize the lookup keys, but {id} renders the ID as the source provided it.
        expected = [f"{i}:{n}" for i, n in zip(source_ids, ["first", "second"], strict=True)]
        assert actual.to_list() == expected

    def test_non_uuid_ids_are_untouched(self):
        translator = self.translator(self.UUIDS)
        series = pd.Series(["not-a-uuid", self.UUIDS[0]], name="src")

        actual = translator.translate(series)

        assert actual.to_list() == ["<Failed: id='not-a-uuid'>", f"{self.UUIDS[0]}:first"]

    def test_transformer_injected_key_survives_the_join(self):
        """A transformer may write keys straight into the backing dict, skipping MagicDict key normalization."""
        injected = "11111111-2222-3333-4444-555555555555"

        class InjectingTransformer(Transformer[str]):
            def update_ids(self, ids, /): ...

            def update_translations(self, translations, /):
                translations[injected] = "injected"  # A str key in an otherwise UUID-keyed dict.

            def try_add_missing_key(self, key, /, *, translations): ...

        data = {"src": {"id": [self.UUIDS[0]], "name": ["first"]}}
        translator: Translator[str, str, str] = Translator(
            data, fmt="{id}:{name}", enable_uuid_heuristics=True, transformers={"src": InjectingTransformer()}
        )

        # Alone, the normalized map is empty; alongside a normal ID, it is not. Both must resolve.
        assert translator.translate(pd.Series([injected], name="src")).to_list() == ["injected"]
        assert translator.translate(pd.Series([self.UUIDS[0], injected], name="src")).to_list() == [
            f"{self.UUIDS[0]}:first",
            "injected",
        ]

    def test_transformer_override_wins_over_the_cast_key(self):
        """A transformer key that collides with a source ID must shadow it, as it does on the scalar path."""
        overridden = self.UUIDS[0]

        class OverridingTransformer(Transformer[str]):
            def update_ids(self, ids, /): ...

            def update_translations(self, translations, /):
                translations[overridden] = "override"  # Collides: `real` also holds UUID(overridden).

            def try_add_missing_key(self, key, /, *, translations): ...

        data = {"src": {"id": [overridden], "name": ["first"]}}
        translator: Translator[str, str, str] = Translator(
            data, fmt="{id}:{name}", enable_uuid_heuristics=True, transformers={"src": OverridingTransformer()}
        )

        # The vectorized path must agree with the scalar one, which resolves the exact key before the cast key.
        assert translator.translate(overridden, names="src") == "override"
        assert translator.translate([overridden], names="src") == ["override"]
        assert translator.translate(pd.Series([overridden], name="src")).to_list() == ["override"]


class TestCategoricalInput:
    """Translating a categorical vector must not change its dtype, whatever the hit/miss ratio."""

    @pytest.fixture
    def translator(self) -> Translator[str, str, int]:
        return Translator({"src": {"id": [1, 2], "name": ["one", "two"]}}, fmt="{id}:{name}")

    @pytest.mark.parametrize(
        "ids, expected",
        [
            ([1, 2], ["1:one", "2:two"]),
            ([1, 99], ["1:one", "<Failed: id=99>"]),
            ([98, 99], ["<Failed: id=98>", "<Failed: id=99>"]),
        ],
        ids=["all-hit", "one-miss", "all-miss"],
    )
    def test_dtype_is_preserved(self, translator, ids, expected):
        actual = translator.translate(pd.Series(ids, name="src", dtype="category"))

        assert isinstance(actual.dtype, pd.CategoricalDtype)
        assert actual.to_list() == expected


@pytest.mark.filterwarnings("ignore::pandas.errors.Pandas4Warning")
class TestObservedCategories:
    """``observed=True`` derives categories from the data, not from everything the fetcher returned."""

    @pytest.fixture
    def ordered_tmap(self) -> TranslationMap[str, str, IdTypes]:
        translations = PlaceholderTranslations.from_dict("s", {1: "c", 2: "a", 3: "a", 10: "b"})
        return TranslationMap(
            source_translations={translations.source: translations},
            fmt="{name}",
            default_fmt="<Failed: id={id}>",
        )

    def test_unused_categories_are_dropped(self, ordered_tmap):
        series = pd.Series([1, 10], name="s")  # ID 2 -> 'a' is never used.
        io = PandasIO[pd.Series](as_category=True, observed=True)
        result = io.insert(series, names=["s"], tmap=ordered_tmap, copy=True)
        assert result is not None

        assert result.cat.categories.to_list() == ["b", "c"]
        assert result.to_list() == ["c", "b"]

    def test_off_by_default(self, ordered_tmap):
        series = pd.Series([1, 10], name="s")
        io = PandasIO[pd.Series](as_category=True)
        result = io.insert(series, names=["s"], tmap=ordered_tmap, copy=True)
        assert result is not None

        assert result.cat.categories.to_list() == ["a", "b", "c"]

    def test_order_is_preserved(self, ordered_tmap):
        series = pd.Series([1, 10], name="s")
        io = PandasIO[pd.Series](as_category=True, ordered="id", observed=True)
        result = io.insert(series, names=["s"], tmap=ordered_tmap, copy=True)
        assert result is not None

        assert result.cat.categories.to_list() == ["c", "b"], "ID order, not alphabetical"
        assert result.dtype.ordered is True

    def test_absent_ids_do_not_decide_order(self):
        """Categories come from the data; an ID that is not in it must not place a translation it shares."""
        translations = PlaceholderTranslations.from_dict("s", {1: "A", 2: "B", 3: "A"})
        tmap: TranslationMap[str, str, int | str] = TranslationMap(
            source_translations={translations.source: translations},
            fmt="{name}",
            default_fmt="<Failed: id={id}>",
        )
        series = pd.Series([2, 3], name="s")  # The absent ID 1 also translates to 'A'.
        io = PandasIO[pd.Series](as_category=True, ordered="id", observed=True)
        result = io.insert(series, names=["s"], tmap=tmap, copy=True)
        assert result is not None

        assert result.cat.categories.to_list() == ["B", "A"]
        assert result.to_list() == ["B", "A"]

    def test_placeholders_are_kept(self, tmap):
        series = pd.Series(["1", "a"], name="str_source")
        io = PandasIO[pd.Series](as_category=True, missing_as_nan=False, observed=True)
        result = io.insert(series, names=["str_source"], tmap=tmap, copy=True)
        assert result is not None

        assert result.cat.categories.to_list() == ["1:StrOne", "<Failed: id=str>"]


@pytest.mark.filterwarnings("ignore::pandas.errors.Pandas4Warning")
def test_nan_ids_do_not_make_category_order_row_dependent():
    """Under `observed` the ID order follows the data, so NaN must not float where it lands."""
    translator: Translator[str, str, int] = Translator({"animals": {0: "Tarzan", 1: "Morris", 2: "Simba"}})
    io_kwargs = {"as_category": True, "observed": True, "missing_as_nan": False, "ordered": "id"}

    first = translator.translate(pd.Series([0.0, float("nan"), 2.0], name="animals"), io_kwargs=io_kwargs)
    shuffled = translator.translate(pd.Series([float("nan"), 0.0, 2.0], name="animals"), io_kwargs=io_kwargs)

    assert first.dtype == shuffled.dtype, "same IDs in a different order must give the same dtype"
    assert list(first.dtype.categories) == ["0:Tarzan", "2:Simba", "<Failed: id=nan>"], "NaN sorts last"


def test_observed_skip_unknown_ids():
    """`missing_as_nan=True` is the default here, so unknown IDs are NaN and must not become a category."""
    translator: Translator[str, str, int] = Translator({"animals": {0: "Tarzan", 1: "Morris", 2: "Simba"}})
    df = pd.DataFrame({"animals": [0, -1, 2]})

    actual = translator.translate(df, io_kwargs={"as_category": True, "observed": True})

    assert actual["animals"].tolist() == ["0:Tarzan", np.nan, "2:Simba"]
    assert actual["animals"].dtype.categories.to_list() == ["0:Tarzan", "2:Simba"], "NaN is not a category"


def test_sorted_ids_groups_incomparable_types_by_name():
    """Types group by name and sort naturally within each group -- not merely "does not crash"."""
    translations: dict[IdTypes, str] = {"b": "x", 2: "y", "a": "z", 10: "w", UUID(int=1): "v"}
    actual = _sorted_ids(translations)

    assert actual == [UUID(int=1), 2, 10, "a", "b"], "grouped by type name, sorted naturally within each"


def test_sorted_ids_orders_several_missing_ids():
    actual = _sorted_ids({pd.NaT: "a", None: "b", pd.NA: "c", 1: "d"})

    assert actual[0] == 1
    assert [str(idx) for idx in actual[1:]] == sorted(["NaT", "None", "<NA>"]), "missing IDs sort among themselves"


@pytest.mark.parametrize("array_like", [[1, 2], (1, 2), np.array([1, 2])])
def test_is_missing_tolerates_array_like_ids(array_like):
    """`pandas.isna` returns an array for these; truth-testing it raises, and that must not escape."""
    assert _is_missing(array_like) is False


@pytest.mark.parametrize("missing", [float("nan"), None, pd.NA, pd.NaT])
def test_sorted_ids_puts_every_null_like_id_last(missing):
    """`pd.NA` raises on truth-testing, so the null check must not rely on comparing the ID to itself."""
    actual = _sorted_ids({missing: "m", 1: "a", 0: "b"})

    assert actual[:2] == [0, 1], "real IDs keep their order"
    assert actual[2] is missing


class TestUuidCategories:
    """The backing dict is keyed by ``UUID``; the input often is not. Categories must survive the mismatch."""

    # Letter-bearing, so the `str.upper` parametrization actually exercises case-insensitive matching.
    UUIDS = [
        "0000000a-bbbb-cccc-dddd-eeeeeeeeeeee",
        "0000000b-bbbb-cccc-dddd-eeeeeeeeeeee",
        "0000000c-bbbb-cccc-dddd-eeeeeeeeeeee",
    ]
    UNKNOWN = "0000dead-bbbb-cccc-dddd-eeeeeeeeeeee"

    @pytest.fixture(scope="class")
    def translator(self) -> Translator[str, str, str]:
        data = {"src": {"id": self.UUIDS, "name": ["first", "second", "third"]}}
        return Translator(data, fmt="{name}", default_fmt="<Failed: id={id}>", enable_uuid_heuristics=True)

    @staticmethod
    def as_kind(kind, ids):
        if kind is pd.DataFrame:
            return pd.DataFrame({"src": ids})
        return kind(ids, name="src")

    @staticmethod
    def dtype_of(kind, translated):
        return translated["src"].dtype if kind is pd.DataFrame else translated.dtype

    @pytest.mark.parametrize("cls", [pd.Series, pd.Index, pd.DataFrame])
    @pytest.mark.parametrize("lookup_kind", [str, str.upper, UUID])
    def test_observed_match_str_input(self, translator, cls, lookup_kind):
        """Filtering on IDs would compare `str` input against `UUID` keys and drop everything."""
        translatable = self.as_kind(cls, [lookup_kind(u) for u in self.UUIDS[:2]])

        actual = translator.translate(translatable, io_kwargs={"as_category": True, "observed": True})

        dtype = self.dtype_of(cls, actual)
        assert isinstance(dtype, pd.CategoricalDtype)
        assert dtype.categories.to_list() == ["first", "second"], "'third' is unused, the rest must survive"
        assert list(actual["src"] if cls is pd.DataFrame else actual) == ["first", "second"]

    @pytest.mark.parametrize("cls", [pd.Series, pd.Index, pd.DataFrame])
    def test_all_categories_are_kept_without_observed(self, translator, cls):
        translatable = self.as_kind(cls, self.UUIDS[:2])

        actual = translator.translate(translatable, io_kwargs={"as_category": True})

        assert self.dtype_of(cls, actual).categories.to_list() == ["first", "second", "third"]

    @pytest.mark.parametrize("observed", [False, True])
    def test_id_order_with_mixed_key_types(self, translator, observed):
        """`extra` is keyed by the input representation, so `real` (UUID) and `extra` (str) keys may mix."""
        series = pd.Series([*self.UUIDS[:2], self.UNKNOWN], name="src")

        actual = translator.translate(
            series,
            io_kwargs={
                "as_category": True,
                "ordered": "id",
                "missing_as_nan": False,
                "observed": observed,
            },
        )

        expected = ["first", "second"] if observed else ["first", "second", "third"]
        assert actual.cat.categories.to_list() == [*expected, f"<Failed: id={self.UNKNOWN}>"]
        assert actual.dtype.ordered is True
