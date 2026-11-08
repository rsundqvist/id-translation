import logging
import warnings
from pathlib import Path

import pytest

from id_translation import Translator
from id_translation.exceptions import ConfigurationError, TranslationWarning
from id_translation.fetching import MemoryFetcher, MultiFetcher
from id_translation.fetching.exceptions import DuplicateSourceError
from id_translation.toml import TranslatorFactory
from id_translation.transform import TransformerStack
from id_translation.transform.types import Transformer

ROOT = Path(__file__).parent
SUFFIX = "tests.transform.test_factory.Suffix"


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

    assert isinstance(translator._tx._transformers["guests"], TransformerStack)

    actual = {"guests": [1991, 1999, 2021]}
    translator.translate(actual, copy=False)

    assert actual == {
        "guests": ["Oh, it's you again Richard.!", "Oh, it's you again Sofia.!", "What's up, Morris?!"],
    }


def test_fetcher_level_transformer():
    translator = Translator[str, str, int].from_config(
        ROOT / "minimal-main.toml", extra_fetchers=[ROOT / "fetcher-and-transformer.toml"]
    )

    assert "guests" not in translator._tx._transformers, "a fetcher's section belongs to the fetcher"

    actual = {"guests": [1991, 1999, 2021]}
    translator.translate(actual, copy=False)

    assert actual == {
        "guests": ["Oh, it's you again Richard.", "Oh, it's you again Sofia.", "What's up, Morris?"],
    }


def _main(tmp_path: Path, extra: str = "", *, conflicts: bool = True) -> Path:
    """A main file without a fetcher of its own, which may transform any source."""
    file = tmp_path / "main.toml"
    multi = '\n[fetching.MultiFetcher]\non_source_conflict = "ignore"\n' if conflicts else ""
    file.write_text('[translator]\nfmt = "{name}"\n' + multi + extra)
    return file


def _aux(tmp_path: Path, tag: str, *, sources: str = "guests", fetcher: str = "MemoryFetcher", extra: str = "") -> Path:
    """An auxiliary file whose fetcher serves `sources`, each named after `tag`, and suffixes `guests` with `-tag`."""
    file = tmp_path / f"{tag}.toml"
    data = "".join(f'{source} = {{ id = [1], name = ["{tag}"] }}\n' for source in sources.split(","))
    file.write_text(
        f"[fetching.'{fetcher}']\n{extra}\n[fetching.'{fetcher}'.data]\n{data}"
        f"\n[fetching.transform.guests.'{SUFFIX}']\nsuffix = \"-{tag}\"\n"
    )
    return file


def _translate(main: Path, *aux: Path) -> list[str]:
    translator = Translator[str, str, int].from_config(main, extra_fetchers=list(aux))
    with warnings.catch_warnings():
        warnings.simplefilter("error", TranslationWarning)
        return translator.translate({"guests": [1]})["guests"]


class TestScope:
    """An auxiliary file's [fetching.transform] goes wherever its fetcher goes: discarded, outranked, or copied.

    See ``TranslatorFactory._handler_transformers``.
    """

    def test_serving_fetcher_applies_its_own(self, tmp_path):
        assert _translate(_main(tmp_path), _aux(tmp_path, "A")) == ["A-A"]

    def test_outranked_fetcher_takes_its_section_with_it(self, tmp_path):
        """Ignoring source conflicts includes the transformers a fetcher brings along, so this is silent."""
        assert _translate(_main(tmp_path), _aux(tmp_path, "A"), _aux(tmp_path, "B")) == ["A-A"]

    def test_fetcher_down_at_discovery_takes_its_section_with_it(self, tmp_path):
        """The outage must not change whose data a section applies to. Silent, like any optional discard."""
        down = _aux(tmp_path, "B", fetcher="tests.transform.test_factory.DownFetcher", extra="optional = true")
        assert _translate(_main(tmp_path), down, _aux(tmp_path, "A")) == ["A-A"]

    def test_fetcher_discarded_at_construction_takes_its_section_with_it(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setenv("ID_TRANSLATION_SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS", "true")
        broken = tmp_path / "B.toml"
        broken.write_text(
            "[fetching.MemoryFetcher]\noptional = true\ndata = 12345\n"
            "\n[fetching.transform.guests.'no.such.module.Nope']\n"
        )

        with caplog.at_level(logging.ERROR):
            assert _translate(_main(tmp_path), broken, _aux(tmp_path, "A")) == ["A-A"]

        (record,) = [r for r in caplog.records if "Discarded optional fetcher" in r.message]
        assert "[fetching.transform]-sections went with it: ['guests']" in record.message
        assert record.dropped_transform == ["guests"]

    def test_two_files_may_transform_the_same_source(self, tmp_path):
        """Each section belongs to its own fetcher, so only the winner's applies; nothing is ambiguous."""
        a, b = _aux(tmp_path, "A"), _aux(tmp_path, "B")
        assert _translate(_main(tmp_path), b, a) == ["B-B"]

    def test_section_for_a_source_the_fetcher_does_not_serve_is_dropped(self, tmp_path):
        main = _main(tmp_path, f"\n[transform.guests.'{SUFFIX}']\nsuffix = \"-MAIN\"\n")
        translator = Translator[str, str, int].from_config(
            main, extra_fetchers=[_aux(tmp_path, "A"), _aux(tmp_path, "B", sources="hosts")]
        )

        with pytest.warns(TranslationWarning, match=r"Dropped \[fetching.transform\]-sections in 'B.toml'") as record:
            assert translator.translate({"guests": [1]}) == {"guests": ["A-A-MAIN"]}
        assert "['guests']" in str(record[0].message)

    def test_promoted_unserved_warning_reproduces(self, tmp_path):
        """Promoted to an error, the retry must report it again rather than settle as if nothing were wrong."""
        translator = Translator[str, str, int].from_config(
            _main(tmp_path), extra_fetchers=[_aux(tmp_path, "A"), _aux(tmp_path, "B", sources="hosts")]
        )

        for _ in range(2):
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                with pytest.raises(TranslationWarning, match="Dropped"):
                    translator.translate({"guests": [1]})

    def test_nested_fetcher_section_for_an_unknown_source_warns(self, tmp_path):
        translator = Translator[str, str, int].from_config(_main(tmp_path), extra_fetchers=[_aux(tmp_path, "A")])
        inner = translator.fetcher
        nested = Translator[str, str, int](MultiFetcher(inner, _aux_fetcher(tmp_path)), fmt="{name}")

        with pytest.warns(TranslationWarning, match=r"never discovered: \['guests'\]\.\nHint: Discovered: \['hosts'\]"):
            nested.translate({"hosts": [1]})

    @pytest.mark.parametrize("how", ["copy", "fresh"])
    def test_copies_keep_the_scope(self, tmp_path, how):
        translator = Translator[str, str, int].from_config(
            _main(tmp_path), extra_fetchers=[_aux(tmp_path, "A"), _aux(tmp_path, "B")]
        )
        if how == "copy":
            translator = translator.copy()
        assert translator.translate({"guests": [1]}) == {"guests": ["A-A"]}


def test_order_is_provided_then_fetcher_section_then_main_section(tmp_path):
    main = _main(tmp_path, f"\n[transform.guests.'{SUFFIX}']\nsuffix = \"-MAIN\"\n", conflicts=False)
    aux = _aux(tmp_path, "A", fetcher="tests.transform.test_factory.ProvidingFetcher")
    assert _translate(main, aux) == ["A-PROVIDED-A-MAIN"]


def test_main_file_fetcher_may_have_its_own_section(tmp_path):
    main = tmp_path / "main.toml"
    main.write_text(
        '[translator]\nfmt = "{name}"\n\n[fetching.MemoryFetcher.data]\nguests = { id = [1], name = ["a"] }\n'
        f"\n[fetching.transform.guests.'{SUFFIX}']\nsuffix = \"-FETCHING\"\n"
        f"\n[transform.guests.'{SUFFIX}']\nsuffix = \"-MAIN\"\n"
    )
    assert _translate(main) == ["a-FETCHING-MAIN"]


def test_main_file_may_transform_any_source(tmp_path):
    main = _main(tmp_path, f"\n[transform.guests.'{SUFFIX}']\nsuffix = \"-MAIN\"\n")
    aux = tmp_path / "A.toml"
    aux.write_text('[fetching.MemoryFetcher.data]\nguests = { id = [1], name = ["a"] }\n')
    assert _translate(main, aux) == ["a-MAIN"]


def test_top_level_transform_in_auxiliary_file_raises(tmp_path):
    aux = tmp_path / "fetcher.toml"
    aux.write_text(
        '[fetching.MemoryFetcher.data]\nguests = { id = [1], name = ["a"] }\n'
        f"\n[transform.guests.'{SUFFIX}']\nsuffix = \"!\"\n"
    )

    with pytest.raises(ConfigurationError, match=r"main file only") as info:
        Translator[str, str, int].from_config(_main(tmp_path), extra_fetchers=[aux])

    notes = getattr(info.value, "__notes__", [])
    assert [n for n in notes if "[fetching.transform.<source>" in n], notes
    assert [n for n in notes if "In file" in n], "the file hint must survive"


def test_fetcher_section_without_a_fetcher_says_where_it_belongs(tmp_path):
    main = _main(tmp_path, f"\n[fetching.transform.guests.'{SUFFIX}']\nsuffix = \"!\"\n")

    with pytest.raises(ConfigurationError, match="belongs to a fetcher declared in the same file") as info:
        Translator[str, str, int].from_config(main, extra_fetchers=[_aux(tmp_path, "A")])
    assert [n for n in getattr(info.value, "__notes__", []) if "top-level [transform]" in n]


def test_optional_main_fetcher_raises(tmp_path):
    main = tmp_path / "main.toml"
    main.write_text("[fetching.MemoryFetcher]\noptional = true\n\n[fetching.MemoryFetcher.data]\ns = { id = [1] }\n")

    with pytest.raises(ConfigurationError, match="main file cannot be optional") as info:
        Translator[str, str, int].from_config(main)

    assert [n for n in getattr(info.value, "__notes__", []) if "auxiliary file" in n]


def test_empty_transform_section(tmp_path):
    file = tmp_path / "main.toml"
    file.write_text(
        '[translator]\nfmt = "{name}"\n\n[transform.guests]\n\n'
        '[fetching.MemoryFetcher.data]\nguests = { id = [1], name = ["a"] }\n'
    )

    with pytest.raises(ConfigurationError, match="must be specified as"):
        Translator[str, str, int].from_config(file)


def test_broken_section_of_a_discarded_fetcher_is_not_built(tmp_path, monkeypatch):
    """A discarded fetcher's transformers often come from the same missing package, so they are never built."""
    monkeypatch.setenv("ID_TRANSLATION_SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS", "true")
    main = tmp_path / "main.toml"
    main.write_text(
        '[translator]\nfmt = "{name}"\n\n[fetching.MemoryFetcher.data]\nguests = { id = [1], name = ["a"] }\n'
        f"\n[transform.guests.'{SUFFIX}']\nsuffix = \"!\"\n"
    )
    aux = tmp_path / "fetcher.toml"
    aux.write_text(
        "[fetching.MemoryFetcher]\noptional = true\ndata = 12345\n\n[fetching.transform.guests.'no.such.module.Nope']\n"
    )

    translator = Translator[str, str, int].from_config(main, extra_fetchers=[aux])

    assert translator.translate({"guests": [1]}) == {"guests": ["a!"]}, "the main file's own section must survive"


@pytest.mark.parametrize(
    "section",
    ["transform = 1", "transform = 'abc'", "transform = []", "transform.guests = 1", "[fetching.transform.guests]"],
)
def test_malformed_section_raises_even_if_its_fetcher_is_discarded(tmp_path, monkeypatch, section):
    """The shape is static configuration, checked before the fetcher is built; only the import waits for it."""
    monkeypatch.setenv("ID_TRANSLATION_SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS", "true")
    aux = tmp_path / "fetcher.toml"
    table = section.startswith("[")
    aux.write_text(
        "[fetching]\n"
        + ("" if table else section + "\n")
        + "[fetching.MemoryFetcher]\noptional = true\ndata = 12345\n"
        + (section + "\n" if table else "")
    )

    with pytest.raises(ConfigurationError, match=r"fetching.transform") as info:
        Translator[str, str, int].from_config(_main(tmp_path), extra_fetchers=[aux])
    assert [n for n in getattr(info.value, "__notes__", []) if "In file" in n], "the file hint must survive"


@pytest.mark.parametrize("in_main_file", [True, False])
def test_broken_transform_does_not_suggest_the_suppress_variable(tmp_path, in_main_file):
    """The variable only skips a section whose fetcher fails to construct; it cannot help with a malformed one."""
    fetching = '[fetching.MemoryFetcher.data]\nguests = { id = [1], name = ["a"] }\n'
    main = tmp_path / "main.toml"
    main.write_text('[translator]\nfmt = "{name}"\n\n' + fetching + ("\n[transform.guests.'no.such.module.Nope']\n"))
    extra = []
    if not in_main_file:
        main.write_text('[translator]\nfmt = "{name}"\n\n' + fetching)
        aux = tmp_path / "fetcher.toml"
        aux.write_text(
            '[fetching.MemoryFetcher.data]\nother = { id = [2], name = ["b"] }\n'
            "\n[fetching.transform.other.'no.such.module.Nope']\n"
        )
        extra.append(aux)

    with pytest.raises(ConfigurationError) as info:
        Translator[str, str, int].from_config(main, extra_fetchers=extra)

    notes = [*getattr(info.value, "__notes__", []), *getattr(info.value.__cause__, "__notes__", [])]
    assert not [note for note in notes if "SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS" in note], notes
    assert [note for note in notes if "In file" in note], "the file hint must survive"


def test_fetcher_file_without_fetching_section(tmp_path):
    file = tmp_path / "fetcher.toml"
    file.write_text("")

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
        extra_fetchers=[ROOT / "fetcher-only.toml", ROOT / "fetcher-only.toml"],
    )

    with pytest.raises(DuplicateSourceError):
        translator.translate({"guests": [1991]})


@pytest.mark.parametrize("first_use", [False, True])
@pytest.mark.parametrize("mode", ["copy", "auto"])
def test_uncopyable_fetcher_section_is_shared_not_the_fetcher(tmp_path, mode, first_use):
    """One uncloneable transformer must not make the whole fetcher, and its connection, shared."""
    aux = _aux(tmp_path, "A")
    aux.write_text(aux.read_text().replace(SUFFIX, "tests.transform.test_factory.UncopyableSuffix"))
    translator = Translator[str, str, int].from_config(_main(tmp_path), extra_fetchers=[aux])
    if first_use:
        translator.translate({"guests": [1]})

    with pytest.warns(TranslationWarning) as record:
        clone = translator.copy(fetcher=mode)
    messages = [str(w.message) for w in record]
    assert [m for m in messages if m.startswith("Failed to clone the [fetching.transform] transformer")], messages
    assert clone.fetcher is not translator.fetcher
    assert clone.translate({"guests": [1]}) == {"guests": ["A-A"]}


def test_copy_keeps_the_config_metadata_with_extra_fetchers(tmp_path):
    translator: Translator[str, str, int] = Translator.from_config(
        _main(tmp_path), extra_fetchers=[_aux(tmp_path, "A")]
    )

    assert translator.copy().config_metadata is translator.config_metadata
    assert translator.copy(transformers={}).config_metadata is translator.config_metadata


@pytest.mark.parametrize("section", ["abc", 123, []])
def test_malformed_transform_root_raises_configuration_error(section):
    with pytest.raises(ConfigurationError, match=r"\[fetching.transform\]-section must contain"):
        TranslatorFactory._handler_transformers(section, section="fetching.transform")


@pytest.mark.parametrize("config", ["abc", 123, [], {}])
def test_malformed_transform_section_raises_configuration_error(config):
    with pytest.raises(ConfigurationError, match="must be specified as"):
        TranslatorFactory._handler_transformers({"guests": config}, section="transform")


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


class UncopyableSuffix(Suffix):
    def __deepcopy__(self, memo):
        raise TypeError("uncopyable")

    def __reduce__(self):
        raise TypeError("unpicklable")


class DownFetcher(MemoryFetcher[str, int]):
    def _initialize_sources(self, task_id):  # noqa: ARG002
        raise ConnectionError("down")


class ProvidingFetcher(MemoryFetcher[str, int]):
    def get_transformer(self, source):
        return Suffix("-PROVIDED") if source == "guests" else None  # type: ignore[abstract]


def _aux_fetcher(tmp_path: Path) -> MemoryFetcher[str, int]:
    """A fetcher serving `hosts` only, with a [fetching.transform] for `guests`, as the factory would build it."""
    file = _aux(tmp_path, "B", sources="hosts")
    translator = Translator[str, str, int].from_config(_main(tmp_path, conflicts=False), extra_fetchers=[file])
    fetcher = translator.fetcher
    assert isinstance(fetcher, MemoryFetcher)
    return fetcher
