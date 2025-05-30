import pandas as pd
import pytest
from rics.misc import serializable

from id_translation import Translator
from id_translation.exceptions import TooManyFailedTranslationsError
from id_translation.fetching import PandasFetcher
from id_translation.transform import BitmaskTransformer

from .conftest import RESOURCES, binary_to_decimal

pytestmark = pytest.mark.parametrize("online", ["online", "offline"])

OVERRIDES = {0: "Private property/no entry 🛑", -1: "Foot-traffic only", 6: "Cool vehicles only", 1: "Automobiles"}


def test_default(online, data):
    transformer = BitmaskTransformer()
    assert transformer._force is False, "defaults changed"
    assert transformer._overrides == {}, "defaults changed"

    translator = make_translator(online, transformer)
    actual = translator.translate(data, names="vehicles").to_dict()
    assert actual == {
        -2: "<Failed: id=np.int64(-2)>",
        -1: "<Failed: id=np.int64(-1)>",
        0: "<Failed: id=np.int64(0)>",
        1: "1:Cars",
        2: "2:Quad bikes",
        3: "1:Cars & 2:Quad bikes",
        4: "4:Skateboards",
        5: "1:Cars & 4:Skateboards",
        6: "2:Quad bikes & 4:Skateboards",
        7: "7:Any four-wheeled vehicle",
        8: "8:Bicycles",
        9: "1:Cars & 8:Bicycles",
        10: "2:Quad bikes & 8:Bicycles",
        11: "1:Cars & 2:Quad bikes & 8:Bicycles",
        12: "12:Any human-powered vehicle",
        13: "1:Cars & 4:Skateboards & 8:Bicycles",
        14: "2:Quad bikes & 4:Skateboards & 8:Bicycles",
        15: "1:Cars & 2:Quad bikes & 4:Skateboards & 8:Bicycles",
        16: "<Failed: id=np.int64(16)>",
    }


def test_overrides(online, data):
    translator = make_translator(online, BitmaskTransformer(overrides=OVERRIDES))
    actual = translator.translate(data, names="vehicles").to_dict()
    assert actual == {
        -2: "<Failed: id=np.int64(-2)>",
        -1: "Foot-traffic only",
        0: "Private property/no entry 🛑",
        1: "Automobiles",
        2: "2:Quad bikes",
        3: "Automobiles & 2:Quad bikes",
        4: "4:Skateboards",
        5: "Automobiles & 4:Skateboards",
        6: "Cool vehicles only",
        7: "7:Any four-wheeled vehicle",
        8: "8:Bicycles",
        9: "Automobiles & 8:Bicycles",
        10: "2:Quad bikes & 8:Bicycles",
        11: "Automobiles & 2:Quad bikes & 8:Bicycles",
        12: "12:Any human-powered vehicle",
        13: "Automobiles & 4:Skateboards & 8:Bicycles",
        14: "2:Quad bikes & 4:Skateboards & 8:Bicycles",
        15: "Automobiles & 2:Quad bikes & 4:Skateboards & 8:Bicycles",
        16: "<Failed: id=np.int64(16)>",
    }


def test_force(online, data):
    translator = make_translator(online, BitmaskTransformer(force_decomposition=True))
    actual = translator.translate(data, names="vehicles").to_dict()
    assert actual == {
        -2: "<Failed: id=np.int64(-2)>",
        -1: "<Failed: id=np.int64(-1)>",
        0: "<Failed: id=np.int64(0)>",
        1: "1:Cars",
        2: "2:Quad bikes",
        3: "1:Cars & 2:Quad bikes",
        4: "4:Skateboards",
        5: "1:Cars & 4:Skateboards",
        6: "2:Quad bikes & 4:Skateboards",
        7: "1:Cars & 2:Quad bikes & 4:Skateboards",
        8: "8:Bicycles",
        9: "1:Cars & 8:Bicycles",
        10: "2:Quad bikes & 8:Bicycles",
        11: "1:Cars & 2:Quad bikes & 8:Bicycles",
        12: "4:Skateboards & 8:Bicycles",
        13: "1:Cars & 4:Skateboards & 8:Bicycles",
        14: "2:Quad bikes & 4:Skateboards & 8:Bicycles",
        15: "1:Cars & 2:Quad bikes & 4:Skateboards & 8:Bicycles",
        16: "<Failed: id=np.int64(16)>",
    }


def test_overrides_take_precedence_over_forced_decomposition(online, data):
    translator = make_translator(online, BitmaskTransformer(overrides=OVERRIDES, force_decomposition=True))
    actual = translator.translate(data, names="vehicles").to_dict()
    assert actual == {
        -2: "<Failed: id=np.int64(-2)>",
        -1: "Foot-traffic only",
        0: "Private property/no entry 🛑",
        1: "Automobiles",
        2: "2:Quad bikes",
        3: "Automobiles & 2:Quad bikes",
        4: "4:Skateboards",
        5: "Automobiles & 4:Skateboards",
        6: "Cool vehicles only",
        7: "Automobiles & 2:Quad bikes & 4:Skateboards",
        8: "8:Bicycles",
        9: "Automobiles & 8:Bicycles",
        10: "2:Quad bikes & 8:Bicycles",
        11: "Automobiles & 2:Quad bikes & 8:Bicycles",
        12: "4:Skateboards & 8:Bicycles",
        13: "Automobiles & 4:Skateboards & 8:Bicycles",
        14: "2:Quad bikes & 4:Skateboards & 8:Bicycles",
        15: "Automobiles & 2:Quad bikes & 4:Skateboards & 8:Bicycles",
        16: "<Failed: id=np.int64(16)>",
    }


class TestMaxFails:
    def test_0_true(self, online):
        with pytest.raises(TooManyFailedTranslationsError):
            self._run(online, 0.0, True)

    def test_1_true(self, online):
        assert self._run(online, 1.0, True) == [
            "2:Quad bikes",
            "4:Skateboards",
            "Cool vehicles only",
            "2:Quad bikes & 8:Bicycles",
            "<Failed: id=33>",
        ]

    def test_0_false(self, online):
        assert self._run(online, 0.0, False) == [
            "2:Quad bikes",
            "4:Skateboards",
            "Cool vehicles only",
            "2:Quad bikes & 8:Bicycles",
            "Automobiles & <Failed: id=32>",
        ]

    def test_1_false(self, online):
        assert self._run(online, 1.0, False) == [
            "2:Quad bikes",
            "4:Skateboards",
            "Cool vehicles only",
            "2:Quad bikes & 8:Bicycles",
            "Automobiles & <Failed: id=32>",
        ]

    @classmethod
    def _run(cls, online: str, max_fails: float, real: bool) -> list[str]:
        transformer = BitmaskTransformer(overrides=OVERRIDES, force_real_translations=real)
        translator = make_translator(online, transformer)
        return translator.translate([2, 4, 6, 10, 33], names="vehicles", max_fails=max_fails)


@pytest.fixture
def data(df):
    bitmask = list(df["bitmask (int)"])
    return pd.Series(
        data=bitmask,
        index=pd.Index(bitmask, name="bitmask"),
        name="permitted vehicles",
    )


def make_translator(online: str, transformer: BitmaskTransformer) -> Translator[str, str, int]:
    fetcher: PandasFetcher[int] = PandasFetcher(
        read_function="read_csv",
        read_path_format=str(RESOURCES / "{}.csv"),
        read_function_kwargs={"converters": {0: binary_to_decimal}},
    )
    ret: Translator[str, str, int] = Translator(fetcher, transformers={"vehicles": transformer})
    assert ret.transformers["vehicles"] is transformer

    if online == "online":
        pass
    elif online == "offline":
        ret.go_offline()
        assert ret.cache.transformers["vehicles"] is transformer
    else:
        raise ValueError(f"{online=}")

    assert serializable(ret)

    return ret
