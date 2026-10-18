import pytest

from id_translation.fetching import MemoryFetcher
from id_translation.fetching.exceptions import ForbiddenOperationError, UnknownPlaceholderError, UnknownSourceError


@pytest.fixture
def fetcher():
    return MemoryFetcher({"source": {"key": [1], "name": ["one"]}})


@pytest.mark.parametrize(("unknown", "expected"), [("id", ("id",)), (("b", "a"), ("b", "a"))])
def test_unknown_placeholders_forms(fetcher, unknown, expected):
    exc = UnknownPlaceholderError.for_placeholders(unknown, placeholders=["name", "key"], source="s", caller=fetcher)
    assert exc.missing_placeholders == expected
    assert exc.placeholders == ("name", "key")
    assert exc.source == "s"


def test_init_accepts_bare_str():
    exc = UnknownPlaceholderError("msg", missing_placeholders="id", placeholders="key")
    assert exc.missing_placeholders == ("id",)
    assert exc.placeholders == ("key",)


def test_message_only():
    exc = UnknownPlaceholderError("text")
    assert str(exc) == "text"
    assert exc.missing_placeholders == ()
    assert exc.placeholders == ()
    assert exc.source is None


def test_message(fetcher):
    exc = UnknownPlaceholderError.for_placeholders(
        ["id", "code"], placeholders=["name", "key"], source="source", caller=fetcher
    )
    assert str(exc) == (
        f"Placeholders ['code', 'id'] not recognized by {fetcher}."
        " For source='source', known placeholders are: ['key', 'name']."
    )


def test_caller_named_by_config_file():
    fetcher: MemoryFetcher[str, int] = MemoryFetcher({"source": {"key": [1]}}, identifiers=["fetchers.toml"])
    exc = UnknownPlaceholderError.for_placeholders("id", placeholders=["key"], source="source", caller=fetcher)
    assert "not recognized by MemoryFetcher (configured in 'fetchers.toml')." in str(exc)


def test_hints_become_notes(fetcher):
    exc = UnknownPlaceholderError.for_placeholders(
        "id", placeholders=["key"], source="source", caller=fetcher, hints="Check the override."
    )
    assert exc.__notes__ == ["Hint: Check the override."]


def test_unknown_sources_message():
    exc = UnknownSourceError.for_sources({"y", "x"}, sources=("b", "a"))
    assert str(exc) == "Sources ['x', 'y'] not recognized. Known sources: ['a', 'b']."
    assert exc.sources == ("b", "a")


def test_forbidden_operation_message():
    cls = "SqlFetcher"
    exc = ForbiddenOperationError.for_operation("FETCH_ALL", fetcher_class=cls)
    assert str(exc) == f"Operation 'FETCH_ALL' is not permitted by {cls}."
    assert exc.operation == "FETCH_ALL"
    assert exc.fetcher_class == cls


def test_unknown_sources_bare_str():
    exc = UnknownSourceError.for_sources("humans", sources="animals")
    assert exc.unknown_sources == ("humans",)
    assert exc.sources == ("animals",)
    assert str(exc) == "Sources ['humans'] not recognized. Known sources: ['animals']."
