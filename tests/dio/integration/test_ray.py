import os

import pytest

# TODO(ray): Remove [tool.ruff.lint.per-file-ignores] rule in pyproject.toml
pytest.mark.skipif(os.getenv("CI") == "true", reason="https://github.com/ray-project/ray/issues/56434")
pytest.importorskip("ray")

import logging
from typing import Any
from uuid import UUID

import numpy as np
import pandas as pd
import ray

from id_translation import Translator
from id_translation.dio import load_integrations
from id_translation.dio.exceptions import NotInplaceTranslatableError
from id_translation.dio.integration.ray import RayIO as _RayIO
from id_translation.dio.integration.ray import RayT
from id_translation.transform import BitmaskTransformer
from id_translation.types import IdTypes

RayIO = _RayIO[RayT, str, IdTypes]
del _RayIO


pytestmark = pytest.mark.filterwarnings("ignore")  # Ray emits a lot of warnings?


@pytest.fixture
def translator() -> Translator[str, str, IdTypes]:
    data = {
        "uuid_strs": {UUID(int=1): "uuid-1", str(UUID(int=2)): "uuid-2"},
        "strs": {"foo": "foo-name", "bar": "bar-name"},
        "ints": {1: "one", 2: "two"},
        "bitmask": {1: "one", 2: "two"},
        "floats": {"id": [1.1], "name": ["float1.1"]},
    }
    return Translator(
        data,
        fmt="{id!s:.8}:{name}",
        transformers={"bitmask": BitmaskTransformer()},  # type: ignore[dict-item]
        enable_uuid_heuristics=True,
    )


@pytest.fixture
def dataset() -> ray.data.Dataset:
    data = {
        # "uuids": [UUID(int=1), UUID(int=2)], # ArrowInvalid
        "uuid_strs": [str(UUID(int=1)), str(UUID(int=2))],
        "strs": ["foo", "bar"],
        "ints": [1, 2],
        "bitmask": [1, 3],
        "floats": [1.1, np.nan],
    }
    df = pd.DataFrame.from_dict(data)
    return ray.data.from_pandas(df)  # Emits warning on unset parameter?!


def test_copy_false_should_provide_hint(dataset, translator):
    with pytest.raises(NotInplaceTranslatableError) as exc_info:
        translator.translate(dataset, copy=False)

    note = exc_info.value.__notes__[1]
    assert "io_kwargs={'copy': False}" in note


def test_names(dataset):
    assert RayIO[ray.data.Dataset]().names(dataset) == ["uuid_strs", "strs", "ints", "bitmask", "floats"]


def test_extract(dataset):
    names = ["uuid_strs", "strs", "ints", "bitmask", "floats"]
    actual = RayIO[ray.data.Dataset]().extract(dataset, names)
    assert actual == {
        "uuid_strs": ["00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"],
        "strs": ["foo", "bar"],
        "ints": [1, 2],
        "bitmask": [1, 3],
        "floats": [1.1],
    }


@pytest.mark.parametrize(
    "batch_format, na_rep",
    [
        ("default", "np.float64(nan)"),
        ("numpy", "np.float64(nan)"),
        ("pandas", "nan"),
        ("pyarrow", "None"),
        (None, "nan"),
    ],
)
def test_known_batch_format_options(dataset, translator, batch_format, na_rep):
    result = translator.translate(dataset, io_kwargs={"batch_format": batch_format})
    assert result.to_pandas().to_dict(orient="list") == {
        "bitmask": ["1:one", "1:one & 2:two"],
        "floats": ["1.1:float1.1", f"<Failed: id={na_rep}>"],
        "ints": ["1:one", "2:two"],
        "strs": ["foo:foo-name", "bar:bar-name"],
        "uuid_strs": ["00000000:uuid-1", "00000000:uuid-2"],
    }


@pytest.mark.parametrize("copy", [False, True])
class TestPandas:
    na_rep = "nan"

    def test_copy(self, translator, dataset, copy):
        io_kwargs = {"batch_format": "pandas", "copy": copy}

        result = translator.translate(dataset, io_kwargs=io_kwargs)
        assert result.to_pandas().to_dict(orient="list") == {
            "bitmask": ["1:one", "1:one & 2:two"],
            "floats": ["1.1:float1.1", f"<Failed: id={self.na_rep}>"],
            "ints": ["1:one", "2:two"],
            "strs": ["foo:foo-name", "bar:bar-name"],
            "uuid_strs": ["00000000:uuid-1", "00000000:uuid-2"],
        }

    # @pytest.mark.xfail(strict=True, reason="https://github.com/ray-project/ray/issues/41974")
    def test_as_category(self, translator, dataset, copy):
        io_kwargs = {"batch_format": "pandas", "copy": copy, "as_category": True}

        result = translator.translate(dataset, io_kwargs=io_kwargs)
        df = result.to_pandas()
        assert all(df.dtypes == "category")
        assert df.to_dict(orient="list") == {
            "bitmask": ["1:one", "1:one & 2:two"],
            "floats": ["1.1:float1.1", np.nan],
            "ints": ["1:one", "2:two"],
            "strs": ["foo:foo-name", "bar:bar-name"],
            "uuid_strs": ["00000000:uuid-1", "00000000:uuid-2"],
        }


@pytest.fixture(autouse=True)
def register():
    assert not RayIO[Any].is_registered(), f"{RayIO.priority=}"

    with pytest.MonkeyPatch().context() as monkeypatch:
        monkeypatch.setattr(RayIO, "priority", -RayIO.priority)

        RayIO[Any].register()
        yield

    load_integrations()


@pytest.fixture(
    scope="session",
    autouse=True,
)
def init(tmp_path_factory):
    logging.getLogger("ray").setLevel(logging.WARNING)
    logging.getLogger("ray.data").setLevel(logging.WARNING)

    os.environ["RAY_USAGE_STATS_ENABLED"] = "0"

    ray.init(
        num_cpus=2,
        include_dashboard=False,
        _temp_dir=str(tmp_path_factory.mktemp("ray-init")),
        _node_name="pytest-id-translation",
    )
    yield
    # ray.shutdown()  # Will sometimes shut down the entire test suite?
