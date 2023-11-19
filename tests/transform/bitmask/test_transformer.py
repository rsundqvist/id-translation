from id_translation.transform import BitmaskTransformer


def test_update_ids(ids):
    assert BitmaskTransformer.update_ids(ids) is None
    assert ids == {-1, 0, 1, 2, 3, 4, 8, 12}
