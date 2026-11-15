import json
import re
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from id_translation.offline.types import PlaceholderTranslations

from ..conftest import ROOT

PATH = str(ROOT.joinpath("imdb/{}.json"))
OPTIONS = ["name_basics", "title_basics"]


@pytest.mark.parametrize("source", OPTIONS)
def test_from_dict(source):
    with open(PATH.format(source)) as f:
        PlaceholderTranslations.from_dict(source, json.load(f))


@pytest.mark.parametrize(
    "data, records",
    [
        ({np.int64(1): "a", np.int64(2): "b"}, ((1, "a"), (2, "b"))),
        ({"id": np.array([1, 2]), "name": ("a", "b")}, ((1, "a"), (2, "b"))),
    ],
)
def test_from_dict_form(data, records):
    assert PlaceholderTranslations.from_dict("s", data).records == records


@pytest.mark.parametrize(
    "data, keys",
    [
        ({1: "a", 2: None}, [2]),
        ({1: "a", 2: 3}, [2]),
        ({"id": [1, 2], "name": "a"}, ["name"]),
        ({1: "a", 2: "b", 3: ["c"]}, [3]),
    ],
)
def test_from_dict_bad_form(data, keys):
    with pytest.raises(TypeError, match=re.escape(f"unexpected values for keys {keys}")):
        PlaceholderTranslations.from_dict("s", data)


def test_from_dict_ragged():
    with pytest.raises(ValueError, match=r"source='s': columns differ in length: \{'id': 2, 'name': 1\}"):
        PlaceholderTranslations.from_dict("s", {"id": [1, 2], "name": ["a"]})  # type: ignore[arg-type]


@pytest.mark.parametrize("source", OPTIONS)
def test_from_data_frame(source):
    df = pd.read_json(PATH.format(source))
    PlaceholderTranslations.from_dataframe(source, df)


@pytest.mark.parametrize("source", OPTIONS)
def test_dict_df_equal(source):
    from_df = PlaceholderTranslations.make(source, pd.read_json(PATH.format(source)))
    from_df = replace(from_df, records=tuple(map(tuple, from_df.records)))

    with open(PATH.format(source)) as f:
        from_dict = PlaceholderTranslations.make(source, json.load(f))

    assert from_df == from_dict


@pytest.mark.parametrize("source", OPTIONS)
def test_to_common_types(source):
    df = pd.read_json(PATH.format(source))
    pht = PlaceholderTranslations.from_dataframe(source, df)

    pd.testing.assert_frame_equal(df, pht.to_pandas())

    assert df.to_dict(orient="list") == pht.to_dict()


def test_to_dicts():
    source_translations = {
        source: PlaceholderTranslations.from_dataframe(source, pd.read_json(PATH.format(source))) for source in OPTIONS
    }

    actual = PlaceholderTranslations.to_dicts(source_translations)

    expected = {}
    for source in OPTIONS:
        with open(PATH.format(source)) as f:
            expected[source] = json.load(f)

    assert actual == expected


def test_make_returns_instance_as_is():
    translations = PlaceholderTranslations("a", ("id", "name"), [(1, "one")])
    assert PlaceholderTranslations.make("a", translations) is translations
