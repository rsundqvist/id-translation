import sys
from pathlib import Path

import pandas as pd
import pytest
from rics.misc import tname

from id_translation.dio import get_resolution_order


@pytest.mark.skipif(sys.platform != "linux", reason="linux only")
def test_ranks():
    order = get_resolution_order()

    records = []
    for i, dio in enumerate(order, start=1):
        record = (
            i,
            dio.priority,
            tname(dio, include_module=True),
            dio.__doc__.partition("\n")[0],  # type: ignore[union-attr]
        )
        records.append(record)

    table = pd.DataFrame.from_records(records, columns=["Rank", "Weight", "Class", "Comment"])
    table["Class"] = table["Class"].map(":class:`~{}`".format)

    path = Path(__file__).parent / "expected-order.csv"
    expected = path.read_text()
    table.to_csv(path, index=False)

    # This table is used in the docs. Verify that it matches reality.
    actual = table.to_csv(index=False)
    assert actual == expected, f"update {path=}"
