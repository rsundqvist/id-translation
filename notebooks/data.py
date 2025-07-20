# flake8: noqa

import re
from pathlib import Path

import pandas as pd
from rics.misc import get_local_or_remote

_LOCAL_ROOT = Path.home() / ".id-translation/notebooks/cache/"
_LOCAL_ROOT.mkdir(parents=True, exist_ok=True)


def _fix_ids(df):
    def integer_group(match):
        return match.group(1)

    columns = _get_id_columns(df)
    for col in columns:
        df[f"int_id_{col}"] = (
            df[col].str.replace(re.compile("^[a-zA-Z]+?([0-9]+)$"), integer_group, regex=True).astype(int)
        )


def _get_id_columns(df):
    return df.columns[df.columns.str.endswith("const")]


def clean_and_fix_ids(input_path) -> pd.DataFrame:
    df = load_pickle(input_path)
    _fix_ids(df)
    return df


def load_pickle(input_path):
    df = pd.read_csv(input_path, sep="\t", header=0, engine="c", low_memory=False)
    any_nan = (df == "\\N").any(axis=1) | df.isna().any(axis=1)
    df = df[~any_nan]
    df = df.apply(pd.to_numeric)
    return df


def load_imdb(dataset):
    remote_root = "https://datasets.imdbws.com"
    file = f"{dataset}.tsv.gz"
    path = get_local_or_remote(file, remote_root=remote_root, local_root=_LOCAL_ROOT, postprocessor=clean_and_fix_ids)
    df = pd.read_pickle(path)
    return df, _get_id_columns(df)
