from uuid import UUID

import pytest

from id_translation.offline import MagicDict
from id_translation.transform.types import Transformer, TransformerStop

FSTRING = "My name is {} and my number is {}."
PLACEHOLDERS = ("name", "id")

REAL_TRANSLATIONS = {
    1991: "My name is Richard and my number is 1991.",
    1999: "My name is Sofia and my number is 1999.",
}


@pytest.mark.parametrize(
    "default_value, expected",
    [
        ("{}", "-1"),
        ("", ""),
        ("longer string", "longer string"),
        ("{} not known", "-1 not known"),
        ("no {} in real", "no -1 in real"),
    ],
)
def test_with_default(default_value, expected):
    subject = MagicDict(REAL_TRANSLATIONS, default_value)

    assert -1 in subject
    assert -321321 in subject
    # Get
    assert subject.get(1991, "get-default") == "My name is Richard and my number is 1991."
    assert subject.get(1999, "get-default") == "My name is Sofia and my number is 1999."
    assert subject.get(-1, "get-default") == expected
    # Getitem
    assert subject[1991] == "My name is Richard and my number is 1991."
    assert subject[1999] == "My name is Sofia and my number is 1999."
    assert subject[-1] == expected


def test_no_default():
    subject = MagicDict(REAL_TRANSLATIONS)

    assert -1 not in subject
    assert -321321 not in subject
    # Get
    assert subject.get(1991, "get-default") == "My name is Richard and my number is 1991."
    assert subject.get(1999, "get-default") == "My name is Sofia and my number is 1999."
    assert subject.get(-1, "get-default") == "get-default"
    # Getitem
    assert subject[1991] == "My name is Richard and my number is 1991."
    assert subject[1999] == "My name is Sofia and my number is 1999."
    with pytest.raises(KeyError):
        subject[-1]


def test_bad_uuids():
    with pytest.raises(TypeError):
        MagicDict(
            {
                "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee": "",
                "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE": "",
            },
            enable_uuid_heuristics=True,
        )


@pytest.mark.parametrize("kind", [str.upper, str.lower, UUID])
def test_uuid_contains_and_delete(kind):
    uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    md = MagicDict(
        {kind(uuid): ""},
        enable_uuid_heuristics=True,
        default_value=None,
    )
    assert uuid in md
    del md[uuid]
    assert uuid not in md


def test_transformer():
    transformer = DummyTransformer()
    subject = MagicDict({0: "ZERO", 1: "ONE"}, transformer=transformer)
    # Should not call missing key yet
    assert transformer.call_counts == {"update_translations": 1, "try_add_missing_key": 0}

    assert subject.get(2) == "TWO"
    assert transformer.call_counts["try_add_missing_key"] == 1
    assert subject[2] == "TWO"
    assert transformer.call_counts["try_add_missing_key"] == 1

    assert subject.get(3) == "THREE"
    assert transformer.call_counts["try_add_missing_key"] == 2
    assert subject[3] == "THREE"
    assert transformer.call_counts["try_add_missing_key"] == 2

    assert subject.get(4) is None
    assert subject.get(5) is None
    assert subject.get(6) is None
    with pytest.raises(KeyError):
        subject.__getitem__(7)

    assert transformer.call_counts == {"update_translations": 1, "try_add_missing_key": DummyTransformer.max_try}
    with pytest.raises(TransformerStop):
        transformer.try_add_missing_key(-1, translations=subject)


class DummyTransformer(Transformer[int]):
    max_try = 3

    def __init__(self):
        self.call_counts = {"update_translations": 0, "try_add_missing_key": 0}

    def update_ids(self, ids):
        pass

    def update_translations(self, translations):
        assert self.call_counts["update_translations"] == 0
        self.call_counts["update_translations"] = 1
        assert translations.get(-1) is None

    def try_add_missing_key(self, key, /, *, translations):
        self.call_counts["try_add_missing_key"] += 1

        if self.call_counts["try_add_missing_key"] >= self.max_try:
            raise TransformerStop()

        if (value := {2: "TWO", 3: "THREE"}.get(key)) is not None:
            translations[key] = value
