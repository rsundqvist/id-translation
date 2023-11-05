import pytest

from id_translation._tasks._names import NamesTask


@pytest.mark.parametrize(
    "reject_predicate, expected",
    [
        (lambda s: not s.endswith("id"), ["ends_with_id", "also_ends_with_id"]),
        (lambda s: "numeric" in s, ["ends_with_id", "also_ends_with_id"]),
        (None, ["ends_with_id", "is_numeric", "also_ends_with_id", "also_numeric"]),
    ],
)
def test_reject_predicates(translator, reject_predicate, expected):
    translatable = {
        "ends_with_id": [1, 2, 3],
        "is_numeric": [3.5, 0.8, 1.1],
        "also_ends_with_id": [1, 2, 3],
        "also_numeric": [3.5, 0.8, 1.1],
    }
    task = NamesTask(translator, translatable=translatable, ignore_names=reject_predicate)
    assert task.mapper_input_names == expected
