from uuid import UUID

import pytest
from id_translation.offline import MagicDict
from id_translation.transform.types import Transformer, TransformerStop


def test_get(monkeypatch):
    real = {1991: "1991:Richard", 1999: "1999:Sofia"}
    subject = MagicDict(real)

    with pytest.raises(AssertionError, match="MagicDict.get is inefficient."):
        subject.get(1)

    monkeypatch.setattr(subject, "get", lambda k, _=None: subject[k])

    # __eq__
    assert subject == real
    assert dict(subject) == real

    # __contains__
    assert -1 in subject
    assert -1 not in dict(subject)
    assert -321321 in subject
    assert -321321 not in dict(subject)

    assert 1991 in subject
    assert 1991 in dict(subject)
    assert 1999 in subject
    assert 1999 in dict(subject)

    # __getitem__
    assert subject[1991] == real[1991]
    assert subject[1999] == real[1999]
    assert subject[-1] == "<Failed: id=-1>"

    # Get = __getitem__
    assert subject.get(1991, "") == subject[1991]
    assert subject.get(1999, "") == subject[1999]
    assert subject.get(-1, "") == subject[-1]

    assert subject.get(1991) == subject[1991]
    assert subject.get(1999) == subject[1999]
    assert subject.get(-1) == subject[-1]


def test_bad_uuids():
    with pytest.raises(TypeError, match="Duplicate UUIDs found."):
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
    md = MagicDict({kind(uuid): ""}, enable_uuid_heuristics=True)
    assert uuid in md


def test_transformer():
    transformer = DummyTransformer()
    subject = MagicDict({0: "ZERO", 1: "ONE"}, transformer=transformer)
    # Should not call missing key yet
    assert transformer.call_counts == {"update_translations": 1, "try_add_missing_key": 0}

    assert subject[2] == "TWO"
    assert transformer.call_counts["try_add_missing_key"] == 1
    assert subject[2] == "TWO"
    assert transformer.call_counts["try_add_missing_key"] == 1

    assert subject[3] == "THREE"
    assert transformer.call_counts["try_add_missing_key"] == 2
    assert subject[3] == "THREE"
    assert transformer.call_counts["try_add_missing_key"] == 2

    assert subject[4] == "<Failed: id=4>"
    assert subject[5] == "<Failed: id=5>"
    assert subject[6] == "<Failed: id=6>"

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
