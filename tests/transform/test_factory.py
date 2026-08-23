import logging
from pathlib import Path

import pytest

from id_translation import Translator
from id_translation.exceptions import ConfigurationError
from id_translation.fetching.exceptions import DuplicateSourceError
from id_translation.toml import TranslatorFactory
from id_translation.transform import TransformerStack
from id_translation.transform.types import Transformer

ROOT = Path(__file__).parent


def test_factory():
    translator = Translator[str, str, int].from_config(ROOT / "main.toml", extra_fetchers=[ROOT / "fetcher-only.toml"])

    actual = {"guests": [1991, 1999, 2021], "drinking_preferences_bitmask": [2, 3, 0]}
    translator.translate(actual, copy=False)

    assert actual == {
        "guests": ["Oh, it's you again Richard.", "Oh, it's you again Sofia.", "What's up, Morris?"],
        "drinking_preferences_bitmask": ["likes tea", "likes coffee AND likes tea", "just water"],
    }


def test_chained():
    translator = Translator[str, str, int].from_config(ROOT / "chained.toml")

    assert isinstance(translator.transformers["guests"], TransformerStack)

    actual = {"guests": [1991, 1999, 2021]}
    translator.translate(actual, copy=False)

    assert actual == {
        "guests": ["Oh, it's you again Richard.!", "Oh, it's you again Sofia.!", "What's up, Morris?!"],
    }


def test_fetcher_level_transformer():
    translator = Translator[str, str, int].from_config(
        ROOT / "minimal-main.toml", extra_fetchers=[ROOT / "fetcher-and-transformer.toml"]
    )

    assert "guests" in translator.transformers, "fetcher-file sections belong to the Translator"

    actual = {"guests": [1991, 1999, 2021]}
    translator.translate(actual, copy=False)

    assert actual == {
        "guests": ["Oh, it's you again Richard.", "Oh, it's you again Sofia.", "What's up, Morris?"],
    }


def test_same_source_in_several_files(tmp_path):
    """Auxiliary files run before the main file, in the order given."""
    main = tmp_path / "main.toml"
    main.write_text(
        '[translator]\nfmt = "{name}"\n\n[fetching.MemoryFetcher.data]\nguests = { id = [1], name = ["a"] }\n'
        "\n[transform.guests.'tests.transform.test_factory.Suffix']\nsuffix = \"-MAIN\"\n"
    )
    aux = []
    for i, tag in enumerate(("AUX1", "AUX2")):
        file = tmp_path / f"{tag}.toml"
        file.write_text(
            f'[fetching.MemoryFetcher.data]\nother{i} = {{ id = [1], name = ["x"] }}\n'
            f"\n[transform.guests.'tests.transform.test_factory.Suffix']\nsuffix = \"-{tag}\"\n"
        )
        aux.append(file)

    translator = Translator[str, str, int].from_config(main, extra_fetchers=aux)

    assert translator.translate({"guests": [1]}) == {"guests": ["a-AUX1-AUX2-MAIN"]}


def test_empty_transform_section(tmp_path):
    file = tmp_path / "main.toml"
    file.write_text(
        '[translator]\nfmt = "{name}"\n\n[transform.guests]\n\n'
        '[fetching.MemoryFetcher.data]\nguests = { id = [1], name = ["a"] }\n'
    )

    with pytest.raises(ConfigurationError, match="must be specified as"):
        Translator[str, str, int].from_config(file)


def test_broken_transform_section_does_not_defeat_optional(tmp_path, monkeypatch):
    """A discarded fetcher's transformers go with it, so they must not be built before the discard check."""
    monkeypatch.setenv("ID_TRANSLATION_SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS", "true")
    main = tmp_path / "main.toml"
    main.write_text(
        '[translator]\nfmt = "{name}"\n\n[fetching.MemoryFetcher.data]\nguests = { id = [1], name = ["a"] }\n'
        "\n[transform.guests.'tests.transform.test_factory.Suffix']\nsuffix = \"!\"\n"
    )
    aux = tmp_path / "fetcher.toml"
    aux.write_text(
        "[fetching.MemoryFetcher]\noptional = true\ndata = 12345\n\n[transform.guests.'no.such.module.Nope']\n"
    )

    translator = Translator[str, str, int].from_config(main, extra_fetchers=[aux])

    assert translator.translate({"guests": [1]}) == {"guests": ["a!"]}, "the main file's own section must survive"


def test_discarded_primary_discards_the_main_transform_section(tmp_path, monkeypatch):
    """The main file's [transform] belongs to its fetcher, exactly as an auxiliary file's does."""
    monkeypatch.setenv("ID_TRANSLATION_SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS", "true")
    main = tmp_path / "main.toml"
    main.write_text(
        '[translator]\nfmt = "{name}"\n\n[fetching.MemoryFetcher]\noptional = true\ndata = 12345\n'
        "\n[transform.guests.'tests.transform.test_factory.Suffix']\nsuffix = \"!\"\n"
    )
    aux = tmp_path / "fetcher.toml"
    aux.write_text('[fetching.MemoryFetcher.data]\nguests = { id = [1], name = ["a"] }\n')

    translator = Translator[str, str, int].from_config(main, extra_fetchers=[aux])

    assert translator.translate({"guests": [1]}) == {"guests": ["a"]}, "the section goes with its fetcher"


def test_broken_main_transform_section_does_not_defeat_optional(tmp_path, monkeypatch):
    """As for auxiliary files: a discarded fetcher's section must not be built at all."""
    monkeypatch.setenv("ID_TRANSLATION_SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS", "true")
    main = tmp_path / "main.toml"
    main.write_text(
        '[translator]\nfmt = "{name}"\n\n[fetching.MemoryFetcher]\noptional = true\ndata = 12345\n'
        "\n[transform.guests.'no.such.module.Nope']\n"
    )
    aux = tmp_path / "fetcher.toml"
    aux.write_text('[fetching.MemoryFetcher.data]\nguests = { id = [1], name = ["a"] }\n')

    translator = Translator[str, str, int].from_config(main, extra_fetchers=[aux])

    assert translator.translate({"guests": [1]}) == {"guests": ["a"]}


@pytest.mark.parametrize("in_main_file", [True, False])
def test_broken_transform_does_not_suggest_the_suppress_variable(tmp_path, in_main_file):
    """The variable only skips a section whose fetcher fails to construct; it cannot help with a malformed one."""
    broken = "\n[transform.guests.'no.such.module.Nope']\n"
    fetching = '[fetching.MemoryFetcher.data]\nguests = { id = [1], name = ["a"] }\n'
    main = tmp_path / "main.toml"
    main.write_text('[translator]\nfmt = "{name}"\n\n' + fetching + (broken if in_main_file else ""))
    extra = []
    if not in_main_file:
        aux = tmp_path / "fetcher.toml"
        aux.write_text('[fetching.MemoryFetcher.data]\nother = { id = [2], name = ["b"] }\n' + broken)
        extra.append(aux)

    with pytest.raises(ConfigurationError) as info:
        Translator[str, str, int].from_config(main, extra_fetchers=extra)

    notes = [*getattr(info.value, "__notes__", []), *getattr(info.value.__cause__, "__notes__", [])]
    assert not [note for note in notes if "SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS" in note], notes
    assert [note for note in notes if "In file" in note], "the file hint must survive"


def test_discarded_fetcher_reports_the_transformers_it_took(tmp_path, monkeypatch, caplog):
    """The reverse mistake warns; dropping a section with its fetcher must not be silent."""
    monkeypatch.setenv("ID_TRANSLATION_SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS", "true")
    main = tmp_path / "main.toml"
    main.write_text(
        '[translator]\nfmt = "{name}"\n\n[fetching.MemoryFetcher]\noptional = true\ndata = 12345\n'
        "\n[transform.guests.'tests.transform.test_factory.Suffix']\nsuffix = \"!\"\n"
    )
    aux = tmp_path / "fetcher.toml"
    aux.write_text('[fetching.MemoryFetcher.data]\nguests = { id = [1], name = ["a"] }\n')

    with caplog.at_level(logging.ERROR):
        Translator[str, str, int].from_config(main, extra_fetchers=[aux])

    records = [r for r in caplog.records if "Discarded optional fetcher" in r.message]
    assert len(records) == 1
    assert "went with it: ['guests']" in records[0].message
    assert records[0].dropped_transform == ["guests"]


def test_fetcher_file_without_fetching_section(tmp_path):
    file = tmp_path / "fetcher.toml"
    file.write_text("[transform.guests.'tests.transform.test_factory.Suffix']\nsuffix = \"!\"\n")

    # Anchored: the "At least one [fetching]-section" fallback would otherwise satisfy this.
    with pytest.raises(ConfigurationError, match=r"^A \[fetching\]-section is required") as info:
        Translator[str, str, int].from_config(ROOT / "minimal-main.toml", extra_fetchers=[file])

    notes = getattr(info.value, "__notes__", [])
    assert [note for note in notes if "In file" in note], "the file hint must survive"
    # A missing section is a config-shape error; no fetcher exists for the suppress variable to discard.
    assert not [note for note in notes if "SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS" in note], notes


def test_source_conflicts_are_left_to_the_multi_fetcher():
    translator = Translator[str, str, int].from_config(
        ROOT / "minimal-main.toml",
        extra_fetchers=[ROOT / "fetcher-and-transformer.toml", ROOT / "fetcher-and-transformer.toml"],
    )

    with pytest.raises(DuplicateSourceError):
        translator.translate({"guests": [1991]})


class SayHi(Transformer[int]):
    def __init__(self, random_seed):
        from random import Random

        self.random = Random(random_seed)

    def update_ids(self, _, /):
        pass

    def update_translations(self, translations, /):
        greetings = ["Oh, it's you again {}.", "Hello {}!", "What's up, {}?"]

        for idx, name in translations.items():
            phrase = self.random.choice(greetings)
            translations[idx] = phrase.format(name)


class Suffix(Transformer[int]):
    def __init__(self, suffix):
        self.suffix = suffix

    def update_ids(self, _, /):
        pass

    def update_translations(self, translations, /):
        for idx in translations:
            translations[idx] += self.suffix


@pytest.mark.parametrize("section", ["abc", 123, []])
def test_malformed_transform_root_raises_configuration_error(section):
    """The section itself, not just a per-source value; the message must name what was given."""
    with pytest.raises(ConfigurationError, match="must contain"):
        TranslatorFactory._handler_transformers(section)


@pytest.mark.parametrize("config", ["abc", 123, [], {}])
def test_malformed_transform_section_raises_configuration_error(config):
    """A non-section value must not escape as a raw AttributeError/TypeError."""
    with pytest.raises(ConfigurationError, match="must be specified as"):
        TranslatorFactory._handler_transformers({"guests": config})
