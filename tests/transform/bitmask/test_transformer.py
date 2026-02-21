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
