import pytest

from id_translation.offline import Format, FormatApplier, MagicDict
from id_translation.offline.types import PlaceholderTranslations


@pytest.fixture(scope="module")
def fmt():
    return Format("{foo} {id}[: baz={baz}]")


def test_no_explicit_placeholders(fmt):
    translations = PlaceholderTranslations("source", ("id", "baz", "foo"), [(1, 1, 3), (2, 2, 4)])
    applier = FormatApplier[str, str, int](translations)

    ans = applier(fmt, default_fmt=Format(""))
    assert isinstance(ans, MagicDict)
    assert ans == {1: "3 1: baz=1", 2: "4 2: baz=2"}


def test_explicit_placeholders(fmt):
    translations = PlaceholderTranslations("source", ("id", "baz", "foo"), [(1, 1, 3), (2, 2, 4)])
    applier = FormatApplier[str, str, int](translations)

    ans = applier(
        fmt,
        default_fmt=Format(""),
        placeholders=("foo", "id"),
        default_fmt_placeholders={"baz": "default-baz", "foo": "default-baz"},
    )
    assert isinstance(ans, MagicDict)
    assert ans == {1: "3 1", 2: "4 2"}


def test_placeholder_wins_over_alias():
    # 'name' and 'title' are both placeholders, and each is also the other's alias.
    aliases = {"name": "title", "title": "name"}
    records = [(1, "Alice", "Dr")]
    translations = PlaceholderTranslations("source", ("id", "name", "title"), records, placeholder_aliases=aliases)
    applier = FormatApplier[str, str, int](translations)

    assert applier(Format("{name}"), default_fmt=Format("")) == {1: "Alice"}
    assert applier(Format("{title}"), default_fmt=Format("")) == {1: "Dr"}
