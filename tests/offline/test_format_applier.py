import pytest

from id_translation.offline import Format, FormatApplier
from id_translation.offline.types import PlaceholderTranslations


@pytest.fixture(scope="module")
def fmt():
    return Format("{foo} {id}[: baz={baz}]")


def test_no_explicit_placeholders(fmt):
    translations = PlaceholderTranslations("source", ("id", "baz", "foo"), [(1, 1, 3), (2, 2, 4)], 0)
    applier: FormatApplier[str, str, int] = FormatApplier(translations)

    ans = applier(fmt)
    assert ans == {1: "3 1: baz=1", 2: "4 2: baz=2"}


def test_explicit_placeholders(fmt):
    translations = PlaceholderTranslations("source", ("id", "baz", "foo"), [(1, 1, 3), (2, 2, 4)], 0)
    applier: FormatApplier[str, str, int] = FormatApplier(translations)

    ans = applier(fmt, ("foo", "id"), default_fmt_placeholders={"baz": "default-baz", "foo": "default-baz"})
    assert ans == {1: "3 1", 2: "4 2"}
