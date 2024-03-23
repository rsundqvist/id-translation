from pathlib import Path

import pandas as pd
import pytest

RESOURCES = Path(__file__).parent / "resources"


@pytest.fixture
def ids(_locations):
    return set(_locations.iloc[:, 0].map(binary_to_decimal))


@pytest.fixture
def translations(_vehicles):
    return {
        0b0001: "Cars",
        0b0010: "Quad bikes",
        0b0100: "Skateboards",
        0b1000: "Bicycles",
        0b0111: "Any four-wheeled vehicle",
        0b1100: "Any human-powered vehicle",
    }


@pytest.fixture(scope="session")
def _locations() -> pd.DataFrame:
    df = pd.read_csv(RESOURCES / "locations.csv")
    df.index = df.iloc[:, 0].map(binary_to_decimal)
    return df


@pytest.fixture(scope="session")
def _vehicles() -> pd.DataFrame:
    return pd.read_csv(RESOURCES / "vehicles.csv")


@pytest.fixture
def df(_locations, _vehicles):
    ret = _locations.reindex(range(-2, 17))
    ret = ret.fillna("-")
    ret["bitmask"] = ret.index.map(lambda x: str(x) if x < 0 else f"0b{x:04b}")
    ret["bitmask (int)"] = ret.index
    ret = ret.reset_index(drop=True)
    return ret


def binary_to_decimal(b):
    if "|" in b:
        # int(b, base=2) doesn't work for '0b01 | 0b10'. Neither does ast.literal_eval().
        left, _, right = b.partition("|")
        return binary_to_decimal(left) | binary_to_decimal(right)
    return int(b, base=2)
