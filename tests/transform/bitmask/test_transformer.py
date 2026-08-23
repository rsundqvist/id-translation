import re

import pytest

from id_translation.transform import BitmaskTransformer


def test_update_ids(ids):
    assert BitmaskTransformer.update_ids(ids) is None
    assert ids == {-1, 0, 1, 2, 3, 4, 8, 12}


def test_eq_and_hash():
    t1 = BitmaskTransformer()
    t2 = BitmaskTransformer()
    assert t1 == t2
    assert hash(t1) == hash(t2)

    t3 = BitmaskTransformer(joiner=" | ")
    assert t3 == BitmaskTransformer(joiner=" | ")
    assert t1 != t3
    assert hash(t1) != hash(t3)

    t4 = BitmaskTransformer(overrides={1: "Override"})
    assert t4 == BitmaskTransformer(overrides={1: "Override"})
    assert t1 != t4
    assert hash(t1) != hash(t4)

    t4_multiple = BitmaskTransformer(overrides={1: "Override1", 2: "Override2"})
    assert t4_multiple == BitmaskTransformer(overrides={2: "Override2", 1: "Override1"})
    assert hash(t4_multiple) == hash(BitmaskTransformer(overrides={2: "Override2", 1: "Override1"}))

    t5 = BitmaskTransformer(force_decomposition=True)
    assert t5 == BitmaskTransformer(force_decomposition=True)
    assert t1 != t5
    assert hash(t1) != hash(t5)

    t6 = BitmaskTransformer(force_real_translations=False)
    assert t6 == BitmaskTransformer(force_real_translations=False)
    assert t1 != t6
    assert hash(t1) != hash(t6)

    assert t1 != "not a transformer"


@pytest.mark.parametrize(
    "record",
    [
        {"override": "missing-id"},
        {"id": 0, "override": "extra-key", "extra": "!"},
    ],
    ids=["missing-key", "extra-key"],
)
def test_from_toml_records_malformed(record):
    records = [{"id": 0, "override": "zero"}, record]
    # {"id", "override"} is process-stable but hash-randomized across runs; build it locally instead of hardcoding.
    permitted = {"id", "override"}
    expected = f"Record 2/2 is malformed: Expected keys {permitted} but got {record}"
    with pytest.raises(ValueError, match=re.escape(expected)):
        BitmaskTransformer(overrides=records)


def test_from_toml_records_duplicate_id():
    records: list[BitmaskTransformer.TomlOverrideRecord] = [
        {"id": 0, "override": "zero"},
        {"id": 1, "override": "one"},
        {"id": 0, "override": "zero-again"},
    ]
    with pytest.raises(ValueError, match=r"Duplicate ID in record 3/3: record="):
        BitmaskTransformer(overrides=records)
