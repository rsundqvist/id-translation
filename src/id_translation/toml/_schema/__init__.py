"""Single source for the published JSON schemas of the TOML configuration format.

The main schema (``id-translation.schema.json``) and metaconf schema (``id-translation-metaconf.schema.json``) are
authored by hand and live next to this module. The auxiliary fetcher-file schema is *derived* from the main schema here,
so the two never drift. The docs build publishes all three; see ``docs/conf.py``.

Private for now: downstream projects that subclass fetchers reference them by fully-qualified name and get the generic
fetcher validation for free, so they don't need this module. Promote to a public name if custom-fetcher schema extension
is requested.
"""

import json
from copy import deepcopy
from importlib.resources import files
from typing import Any

_PACKAGE = "id_translation.toml._schema"
_BASE_URL = "https://id-translation.readthedocs.io/en/stable/"

MAIN_FILENAME = "id-translation.schema.json"
FETCHER_FILENAME = "id-translation-fetcher.schema.json"
METACONF_FILENAME = "id-translation-metaconf.schema.json"


def _load(filename: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((files(_PACKAGE) / filename).read_text(encoding="utf-8"))
    return data


def derive_fetcher_schema(main: dict[str, Any]) -> dict[str, Any]:
    schema = deepcopy(main)
    schema["$id"] = _BASE_URL + FETCHER_FILENAME
    schema["title"] = "id-translation fetcher configuration"
    schema["description"] = (
        "Schema for id-translation auxiliary fetcher files, which may only contain the top-level `fetching` section; "
        "transformers go in `[fetching.transform]`. "
        "See https://id-translation.readthedocs.io/en/stable/documentation/translator-config.html"
    )
    schema["properties"] = {"fetching": {"$ref": "#/definitions/fetching"}}
    schema["required"] = ["fetching"]
    # Forbid MultiFetcher in fetcher files. The key is kept in `properties` set to `false` (rejecting any value);
    # popping it would instead let the permissive `additionalProperties` accept it as a generic custom fetcher.
    schema["definitions"]["fetching"]["properties"]["MultiFetcher"] = False
    # Only an auxiliary file's fetcher may be optional.
    schema["definitions"]["fetcherCommon"]["properties"]["optional"] = {
        "type": "boolean",
        "description": "If true, discard the fetcher when source discovery raises, e.g. because a database is down. "
        "Configuration errors still raise, unless ID_TRANSLATION_SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS is set and the "
        "fetcher fails to construct.",
    }
    return schema


def published_schemas() -> dict[str, dict[str, Any]]:
    """Return every schema to publish, keyed by output filename."""
    main = _load(MAIN_FILENAME)
    return {
        MAIN_FILENAME: main,
        FETCHER_FILENAME: derive_fetcher_schema(main),
        METACONF_FILENAME: _load(METACONF_FILENAME),
    }
