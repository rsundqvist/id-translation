import copy
import json
from datetime import datetime, timedelta
from importlib.metadata import PackageNotFoundError

import pytest

from id_translation import Translator
from id_translation.toml.exceptions import ConfigFileError
from id_translation.toml.meta import ConfigMetadata, Metaconf, _base_metadata

from .conftest import ROOT


@pytest.fixture
def metadata():
    return ConfigMetadata.from_toml_paths(ROOT / "config.toml", clazz=Translator)


def test_json_round_trip(metadata):
    """A naive `created` is read as local time and stored as aware UTC."""
    given = datetime(2026, 1, 15, 12)  # Far from any DST change.
    naive = type(metadata)(**{**metadata.__dict__, "created": given})

    restored = ConfigMetadata.from_json(naive.to_json())
    assert restored == naive
    assert restored.created == given.astimezone()
    assert restored.created.utcoffset() == timedelta(0)


def test_from_json_rejects_unknown_keys(metadata):
    """Checked by an assert before, which ``python -O`` removes."""
    s = json.dumps({**json.loads(metadata.to_json()), "extra": 1})
    with pytest.raises(ValueError, match=r"^Unknown keys: \['extra'\]\.$"):
        ConfigMetadata.from_json(s)


def test_from_json_rejects_bad_versions(metadata):
    s = json.dumps({**json.loads(metadata.to_json()), "versions": []})
    with pytest.raises(TypeError, match=r"^Bad versions=\[\]: expected a dict\.$"):
        ConfigMetadata.from_json(s)


def test_from_toml_paths_takes_one_bare_extra_fetcher(tmp_path):
    fetcher = tmp_path / "fetcher.toml"
    fetcher.write_text("[fetching.MemoryFetcher.data.s]\nid = [1]\n", encoding="utf-8")

    metadata = ConfigMetadata.from_toml_paths(ROOT / "config.toml", str(fetcher), clazz=Translator)
    assert [p for p, _ in metadata.extra_fetchers] == [fetcher]


def test_reason_not_equivalent_names_a_changed_version(metadata):
    other = type(metadata)(**{**metadata.__dict__, "versions": {**metadata.versions, "id-translation": "0.0.0"}})

    assert metadata.reason_not_equivalent(metadata) == ""
    expected = metadata.versions["id-translation"]
    assert metadata.reason_not_equivalent(other) == (
        f"Expected id-translation={expected!r} (your environment) but got id-translation='0.0.0'"
    )


_AUX = ROOT / "aux.toml"
_MAIN = ROOT / "main.toml"


@pytest.mark.parametrize(
    ("changes", "expected", "reverse"),
    [
        (
            {"clazz": "other.Translator"},
            "Class not equal. Expected '{clazz}', but got 'other.Translator'",
            "Class not equal. Expected 'other.Translator', but got '{clazz}'",
        ),
        (
            {"main": (_MAIN, "changed")},
            "Main configuration changed: {main}",
            "Main configuration changed: {other_main}",
        ),
        (
            {"extra_fetchers": ((_AUX, "a"),)},
            "Number of auxiliary fetchers changed. Expected 0 fetchers but got 1",
            "Number of auxiliary fetchers changed. Expected 1 fetchers but got 0",
        ),
        (
            {"metaconf": Metaconf.from_dict({"env": {"allow_blank": True}})},
            "Meta configuration changed: env.allow_blank: True -> False",
            "Meta configuration changed: env.allow_blank: False -> True",
        ),
    ],
)
def test_reason_not_equivalent_in_both_directions(metadata, changes, expected, reverse):
    other = type(metadata)(**{**metadata.__dict__, **changes})
    names = {"clazz": metadata.clazz, "main": metadata.main[0], "other_main": _MAIN}
    assert metadata.reason_not_equivalent(other) == expected.format(**names)
    assert other.reason_not_equivalent(metadata) == reverse.format(**names)


def test_reason_not_equivalent_compares_fingerprints_not_paths(metadata):
    moved = type(metadata)(**{**metadata.__dict__, "main": (ROOT / "moved.toml", metadata.main[1])})
    changed = type(metadata)(**{**metadata.__dict__, "main": (metadata.main[0], "changed")})
    assert metadata.reason_not_equivalent(moved) == moved.reason_not_equivalent(metadata) == ""
    assert metadata.reason_not_equivalent(changed) == f"Main configuration changed: {metadata.main[0]}"


def test_reason_not_equivalent_names_a_changed_auxiliary_file(metadata):
    first = type(metadata)(**{**metadata.__dict__, "extra_fetchers": ((_AUX, "a"),)})
    second = type(metadata)(**{**metadata.__dict__, "extra_fetchers": ((_AUX, "b"),)})
    assert first.reason_not_equivalent(second) == f"Auxiliary fetcher configuration #1 changed: {_AUX}"
    assert second.reason_not_equivalent(first) == f"Auxiliary fetcher configuration #1 changed: {_AUX}"
    assert first.reason_not_equivalent(first) == ""


def test_metaconf_from_dict_does_not_mutate_input():
    config = {"env": {"allow_blank": True}, "equivalence": {"extra_packages": ["rics"]}}
    expected = copy.deepcopy(config)

    metaconf = Metaconf.from_dict(config)

    assert config == expected
    assert metaconf.equivalence.extra_packages == ["rics"]


def test_metaconf_unknown_key():
    with pytest.raises(TypeError, match=r"Unknown keys: \['envv'\]"):
        Metaconf.from_dict({"envv": {}})


def test_toml_date_literals(tmp_path):
    def fingerprint(value: str) -> str:
        path = tmp_path / "config.toml"
        path.write_text(f"[fetching.MemoryFetcher.data.holidays]\nid = [1]\nname = [{value}]\n", encoding="utf-8")
        return ConfigMetadata.from_toml_paths(path, clazz=Translator).main[1]

    assert fingerprint("2026-12-24") != fingerprint('"2026-12-24"')
    assert fingerprint("12:30:00") != fingerprint('"12:30:00"')


def test_reordered_transformers_change_the_fingerprint(tmp_path):
    """Transformers are chained in declaration order, so a reorder can change translations."""
    first = '[transform.s.First]\nkey = "a"\n'
    second = '[transform.s.Second]\nkey = "b"\n'

    def fingerprint(transform: str) -> str:
        path = tmp_path / "config.toml"
        path.write_text(f"[fetching.MemoryFetcher.data.s]\nid = [1]\n\n{transform}", encoding="utf-8")
        return ConfigMetadata.from_toml_paths(path, clazz=Translator).main[1]

    assert fingerprint(first + second) != fingerprint(second + first)


def test_changed_metaconf_names_the_changed_keys(metadata):
    current = copy.deepcopy(metadata)
    current.metaconf = Metaconf.from_dict({"env": {"allow_blank": True}})

    reason = current.reason_not_equivalent(metadata)
    assert reason == "Meta configuration changed: env.allow_blank: False -> True"


@pytest.mark.parametrize(
    ("toml", "match"),
    [
        ("[env]\nallow_interpolation = 'false'\n", "allow_interpolation"),
        ("env = 'x'\n", r"bad env='x': expected a table"),
        ("equivalence = 'ab'\n", r"bad equivalence='ab': expected a table"),
        ("equivalence = []\n", r"bad equivalence=\[\]: expected a table"),
        ("[equivalence]\npython_version = '{v.nope}'\n", "python_version"),
        ("[equivalence]\npython_version = '{'\n", "python_version"),
        ("[equivalence]\npython_version = 3\n", "python_version"),
        ("[equivalence]\npython_version = '{v:%Y}'\n", "python_version"),
    ],
)
def test_metaconf_type_error_is_a_config_file_error(tmp_path, toml, match):
    path = tmp_path / "metaconf.toml"
    path.write_text(toml, encoding="utf-8")
    with pytest.raises(ConfigFileError, match=match) as exc_info:
        Metaconf.from_path_or_default(path)
    assert exc_info.value.__notes__ == [f"Hint: In file: {path.resolve()}"]


def test_metaconf_unknown_key_names_the_file(tmp_path):
    path = tmp_path / "metaconf.toml"
    path.write_text("[envv]\nallow_interpolation = false\n", encoding="utf-8")
    with pytest.raises(ConfigFileError) as exc_info:
        Metaconf.from_path_or_default(path)
    assert str(exc_info.value).startswith("TypeError: Unknown keys")
    assert exc_info.value.__notes__ == [f"Hint: In file: {path.resolve()}"]


def test_metaconf_package_check_skipped_with_old_packaging(tmp_path, monkeypatch):
    packaging_utils = pytest.importorskip("packaging.utils")
    monkeypatch.delattr(packaging_utils, "InvalidName")  # Added in packaging 23.2.

    path = tmp_path / "metaconf.toml"
    path.write_text("[equivalence]\nextra_packages = ['rics']\n", encoding="utf-8")
    assert Metaconf.from_path_or_default(path).equivalence.extra_packages == ["rics"]


@pytest.mark.parametrize("value", ["'rics'", "{rics = 'ignored'}", "5"])
def test_metaconf_extra_packages_must_be_an_array(tmp_path, value):
    path = tmp_path / "metaconf.toml"
    path.write_text(f"[equivalence]\nextra_packages = {value}\n", encoding="utf-8")
    with pytest.raises(ConfigFileError, match=r"expected list\[str\]"):
        Metaconf.from_path_or_default(path)


def test_extra_package_that_is_not_installed_names_metaconf(tmp_path):
    metaconf_path = tmp_path / "metaconf.toml"
    metaconf_path.write_text("[equivalence]\nextra_packages = ['no-such-distribution']\n", encoding="utf-8")
    main = tmp_path / "main.toml"
    main.write_text("", encoding="utf-8")
    with pytest.raises(PackageNotFoundError) as exc_info:
        ConfigMetadata.from_toml_paths(main, clazz=Translator)
    assert exc_info.value.__notes__ == [f"Hint: In file: {metaconf_path.resolve()}"]


def test_id_translation_without_metadata_names_no_file(tmp_path, monkeypatch):
    """A vendored install without metadata has no version; metaconf.toml, which may not exist, is not why."""

    def get_version(name: str) -> str:
        raise PackageNotFoundError(name)

    monkeypatch.setattr(_base_metadata, "get_version", get_version)
    main = tmp_path / "main.toml"
    main.write_text("", encoding="utf-8")
    with pytest.raises(PackageNotFoundError) as exc_info:
        ConfigMetadata.from_toml_paths(main, clazz=Translator)
    assert not hasattr(exc_info.value, "__notes__")
