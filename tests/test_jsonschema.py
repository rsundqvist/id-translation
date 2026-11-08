"""Guards against the bundled JSON schemas drifting from the runtime grammar."""

import inspect
from dataclasses import fields
from typing import Any, get_args

import jsonschema

from id_translation import fetching
from id_translation.fetching._multi_fetcher import OnSourceConflict
from id_translation.mapping import Cardinality, Mapper
from id_translation.mapping.types import OnUnknownUserOverride, OnUnmapped
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
    assert set(fetcher["properties"]) == {"fetching"}, "transformers go in [fetching.transform]"
    assert fetcher["required"] == ["fetching"]
    # MultiFetcher is permitted in the main configuration file only; fetcher files reject it (schema `false`).
    assert fetcher["definitions"]["fetching"]["properties"]["MultiFetcher"] is False


def test_cache_grammar() -> None:
    validator = jsonschema.Draft7Validator(schemas()[MAIN_FILENAME]["definitions"]["cache"])

    assert validator.is_valid({"my.lib.MyCacheAccess": {"ttl": 3600}})
    assert validator.is_valid({"my.lib.MyCacheAccess": {}})

    assert not validator.is_valid({})
    assert not validator.is_valid({"ttl": 3600}), "not a type section"
    assert not validator.is_valid({"a.A": {}, "b.B": {}}), "one implementation only"
    assert not validator.is_valid({"type": "my.lib.MyCacheAccess", "ttl": 3600}), "the 1.x type= key is rejected"


def test_metaconf_top_level_matches_dataclass() -> None:
    metaconf = schemas()[METACONF_FILENAME]
    assert set(metaconf["properties"]) == {f.name for f in fields(Metaconf)}


def test_enumerated_builtin_fetchers_exist() -> None:
    # Every enumerated built-in fetcher must be a real id_translation.fetching class.
    main = schemas()[MAIN_FILENAME]
    reserved = {"mapping", "cache", "transform", "MultiFetcher"}
    builtins = set(main["definitions"]["fetching"]["properties"]) - reserved
    assert builtins, "expected built-in fetchers to be enumerated"
    for name in builtins:
        assert hasattr(fetching, name), name


def test_enums_match_runtime() -> None:
    definitions = schemas()[MAIN_FILENAME]["definitions"]
    mapping = definitions["mapping"]["properties"]
    assert mapping["cardinality"]["enum"] == [c.value for c in Cardinality] + [c.name for c in Cardinality]
    assert mapping["on_unmapped"]["enum"] == list(get_args(OnUnmapped))
    assert mapping["on_unknown_user_override"]["enum"] == list(get_args(OnUnknownUserOverride))
    assert definitions["multiFetcher"]["properties"]["on_source_conflict"]["enum"] == list(get_args(OnSourceConflict))


def test_mapping_keys_are_mapper_parameters() -> None:
    mapping = schemas()[MAIN_FILENAME]["definitions"]["mapping"]["properties"]
    parameters = set(inspect.signature(Mapper).parameters)
    # The TOML handler builds these from list-subsections instead of passing them as-is.
    assert set(mapping) - parameters == {"score_function_heuristics"}
    assert parameters - set(mapping) == {"score_function_kwargs"}


def test_required_fetcher_keys_have_no_default() -> None:
    definitions = schemas()[MAIN_FILENAME]["definitions"]
    for name in ["memoryFetcher", "pandasFetcher", "sqlFetcher"]:
        cls = getattr(fetching, name[0].upper() + name[1:])
        without_default = {
            p.name
            for p in inspect.signature(cls).parameters.values()
            if p.default is p.empty and p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)
        }
        assert set(definitions[name].get("required", [])) == without_default, name


def test_transform_scopes() -> None:
    section = {"guests": {"my.lib.Suffix": {"suffix": "!"}}}
    fetching = {"MemoryFetcher": {"data": {}}, "transform": section}
    main = jsonschema.Draft7Validator(schemas()[MAIN_FILENAME])
    fetcher = jsonschema.Draft7Validator(schemas()[FETCHER_FILENAME])

    assert main.is_valid({"fetching": fetching, "transform": section})
    assert fetcher.is_valid({"fetching": fetching})
    assert not fetcher.is_valid({"fetching": fetching, "transform": section}), "main file only"
    assert not main.is_valid({"fetching": {**fetching, "transform": 1}}), "not taken for a custom fetcher type"


def test_runtime_rejected_keys() -> None:
    main = jsonschema.Draft7Validator(schemas()[MAIN_FILENAME])
    fetcher = jsonschema.Draft7Validator(schemas()[FETCHER_FILENAME])
    memory: dict[str, Any] = {"data": {}}

    assert main.is_valid({"fetching": {"MemoryFetcher": memory, "mapping": {"cardinality": "OneToOne"}}})
    assert not main.is_valid({"translator": {"mapping": {"score_function_kwargs": {}}}}), "use a score_function table"
    assert not main.is_valid({"fetching": {"MemoryFetcher": {**memory, "mapper": {}}}}), "use [fetching.mapping]"
    assert not main.is_valid({"fetching": {"my.lib.Fetcher": {"cache_access": {}}}}), "use [fetching.cache.'<type>']"

    optional = {"fetching": {"MemoryFetcher": {**memory, "optional": True}}}
    assert not main.is_valid(optional), "the main file's fetcher cannot be optional"
    assert fetcher.is_valid(optional)
