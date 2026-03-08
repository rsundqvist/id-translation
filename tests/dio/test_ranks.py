import sys
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest
from rics.misc import tname

from id_translation.dio import _repository, get_resolution_order


@pytest.mark.skipif(sys.platform != "linux", reason="linux only")
def test_ranks(annotations):
    order = get_resolution_order()

    records = []
    for i, dio in enumerate(order, start=1):
        record = (
            i,
            dio.priority,
            tname(dio, include_module=True),
            annotations[dio],
            dio.__doc__.partition("\n")[0],  # type: ignore[union-attr]
        )
        records.append(record)

    table = pd.DataFrame.from_records(records, columns=["Rank", "Weight", "Class", "__tmp_notes__", "Comment"])
    table["Class"] = table["Class"].map(":class:`~{}` ".format) + table["__tmp_notes__"]
    table["Class"] = table["Class"].str.strip()
    del table["__tmp_notes__"]

    path = Path(__file__).parent / "expected-order.csv"
    expected = path.read_text()
    table.to_csv(path, index=False)

    # This table is used in the docs. Verify that it matches reality.
    actual = table.to_csv(index=False)
    assert actual == expected, f"update {path=}"


@pytest.fixture
def annotations(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[_repository.AnyIoType, str]]:
    per_cls: dict[_repository.AnyIoType, list[str]] = {}

    all_ios = _repository.get_repository().all_ios
    assert len(all_ios) == 7

    for io_class in all_ios:
        anns = per_cls[io_class] = []

        if io_class.priority < 0:
            anns.append("[#explicit]_")
        elif io_class.__module__.startswith("id_translation.dio.integration."):
            anns.append("[#automatic]_")

        monkeypatch.setattr(io_class, "priority", abs(io_class.priority))

    tmp_repo = _repository.Repository(ios=all_ios, load_integrations=False, load_defaults=False)
    monkeypatch.setattr(_repository, "_INSTANCE", tmp_repo)

    yield {k: " ".join(v) for k, v in per_cls.items()}
