import pytest

from id_translation.offline import MagicDict

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
