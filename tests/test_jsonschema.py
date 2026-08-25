"""Guards against the bundled JSON schemas drifting from the runtime grammar."""

from dataclasses import fields
from typing import Any

import pytest

from id_translation import fetching
from id_translation.toml import TranslatorFactory
from id_translation.toml._schema import (
    FETCHER_FILENAME,
    MAIN_FILENAME,
    METACONF_FILENAME,
    published_schemas,
)
from id_translation.toml.meta import Metaconf


def schemas() -> dict[str, dict[str, Any]]:
    return published_schemas()


def test_all_are_draft07() -> None:
    for name, schema in schemas().items():
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#", name
        assert schema["type"] == "object", name
        assert schema["additionalProperties"] is False, name


def test_main_top_level_matches_factory() -> None:
    main = schemas()[MAIN_FILENAME]
    assert set(main["properties"]) == set(TranslatorFactory.TOP_LEVEL_KEYS)


def test_fetcher_top_level_matches_aux_allow_list() -> None:
    # Auxiliary fetcher files allow only these at the root; see TranslatorFactory._handle_fetching.
    fetcher = schemas()[FETCHER_FILENAME]
    assert set(fetcher["properties"]) == {"fetching", "transform"}
    # A transform-only fetcher file is a ConfigurationError at load time; the schema must reject it too.
    assert fetcher["required"] == ["fetching"]
    # MultiFetcher is permitted in the main configuration file only; fetcher files reject it (schema `false`).
    assert fetcher["definitions"]["fetching"]["properties"]["MultiFetcher"] is False


def test_cache_accepts_both_grammars() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft7Validator(schemas()[MAIN_FILENAME]["definitions"]["cache"])

    assert validator.is_valid({"my.lib.MyCacheAccess": {"ttl": 3600}})
    assert validator.is_valid({"my.lib.MyCacheAccess": {}})
    assert validator.is_valid({"type": "my.lib.MyCacheAccess", "ttl": 3600}), "deprecated since 1.3.0"

    assert not validator.is_valid({})
    assert not validator.is_valid({"ttl": 3600}), "neither grammar"
    assert not validator.is_valid({"a.A": {}, "b.B": {}}), "one implementation only"
    assert not validator.is_valid({"type": "my.lib.MyCacheAccess", "my.lib.MyCacheAccess": {}}), "half-migrated"


def test_metaconf_top_level_matches_dataclass() -> None:
    metaconf = schemas()[METACONF_FILENAME]
    assert set(metaconf["properties"]) == {f.name for f in fields(Metaconf)}


def test_enumerated_builtin_fetchers_exist() -> None:
    # Every enumerated built-in fetcher must be a real id_translation.fetching class.
    main = schemas()[MAIN_FILENAME]
    reserved = {"mapping", "cache", "MultiFetcher"}
    builtins = set(main["definitions"]["fetching"]["properties"]) - reserved
    assert builtins, "expected built-in fetchers to be enumerated"
    for name in builtins:
        assert hasattr(fetching, name), name
