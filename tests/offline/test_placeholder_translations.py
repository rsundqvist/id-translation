import json

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


@pytest.mark.parametrize("source", OPTIONS)
def test_from_data_frame(source):
    df = pd.read_json(PATH.format(source))
    PlaceholderTranslations.from_dataframe(source, df)


@pytest.mark.parametrize("source", OPTIONS)
def test_dict_df_equal(source):
    from_df = PlaceholderTranslations.make(source, pd.read_json(PATH.format(source)))

    with open(PATH.format(source)) as f:
        from_dict = PlaceholderTranslations.make(source, json.load(f))

    assert from_df == from_dict


def test_to_dict():
    source = OPTIONS[0]
    df = pd.read_json(PATH.format(source))
    PlaceholderTranslations.from_dataframe(source, df).to_dict()


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
