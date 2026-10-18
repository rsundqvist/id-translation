"""A source that lacks a placeholder required by ``fmt`` raises ``MissingPlaceholderError``, online or offline."""

import pytest

from id_translation import Translator
from id_translation.exceptions import MissingIdPlaceholderError, MissingPlaceholderError
from id_translation.fetching import MemoryFetcher
from id_translation.fetching.exceptions import UnknownIdPlaceholderError, UnknownPlaceholderError
from id_translation.offline import Format, FormatApplier
from id_translation.offline.types import PlaceholderTranslations

DATA = {"staff": {"id": [1], "name": ["Ada"], "team": ["sales"]}}


def test_offline_snapshot_without_placeholder():
    translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA), fmt="{id}:{name}")
    translator.go_offline()

    with pytest.raises(MissingPlaceholderError, match=r"lacks placeholders \['team'\]") as exc_info:
        translator.translate(1, names="staff", fmt="{name} ({team})")

    exc = exc_info.value
    assert type(exc) is MissingPlaceholderError
    assert exc.missing_placeholders == ("team",)
    assert exc.placeholders == ("id", "name")
    assert exc.source == "staff"


def test_offline_snapshot_with_optional_placeholder():
    translator: Translator[str, str, int] = Translator(MemoryFetcher(DATA), fmt="{id}:{name}[ ({team})]")
    translator.go_offline()
    assert translator.translate(1, names="staff", fmt="{name} ({team})") == "Ada (sales)"


def test_inline_data_without_placeholder():
    translator: Translator[str, str, int] = Translator({"staff": {"id": [1], "name": ["Ada"]}})
    with pytest.raises(MissingPlaceholderError):
        translator.translate(1, names="staff", fmt="{name} ({team})")


def test_online_raises_subclass():
    translator: Translator[str, str, int] = Translator(MemoryFetcher({"staff": {"id": [1], "name": ["Ada"]}}))
    with pytest.raises(MissingPlaceholderError) as exc_info:
        translator.translate(1, names="staff", fmt="{name} ({team})")

    assert isinstance(exc_info.value, UnknownPlaceholderError)
    assert exc_info.value.missing_placeholders == ("team",)


def test_id_errors_are_missing_placeholder_errors():
    assert issubclass(MissingIdPlaceholderError, MissingPlaceholderError)
    assert MissingIdPlaceholderError("msg").missing_placeholders == ("id",)
    assert UnknownIdPlaceholderError("msg").missing_placeholders == ("id",)

    exc = UnknownPlaceholderError.for_placeholders("id", placeholders="name", source="s", caller=MemoryFetcher({}))
    assert isinstance(exc, UnknownIdPlaceholderError)
    assert exc.missing_placeholders == ("id",)
    assert exc.placeholders == ("name",)


def test_explicit_placeholders_are_checked_against_the_source():
    applier: FormatApplier[str, str, int] = FormatApplier(
        PlaceholderTranslations.make("staff", {"id": [1], "name": ["Ada"]})
    )
    default_fmt = Format("<{id}>")

    with pytest.raises(MissingPlaceholderError, match=r"lacks placeholders \['team'\]"):
        applier.apply(Format("{id}:{name}[ ({team})]"), default_fmt=default_fmt, placeholders=("id", "name", "team"))

    for placeholders in [(), ("id",), ("id", "name"), ("name", "id"), ("name", "id", "unused")]:
        translations = applier.apply(Format("{id}:{name}"), default_fmt=default_fmt, placeholders=placeholders)
        assert translations[1] == "1:Ada", placeholders
