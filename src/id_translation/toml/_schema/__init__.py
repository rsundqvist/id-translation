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
    data: dict[str, Any] = json.loads((files(_PACKAGE) / filename).read_text())
    return data


def derive_fetcher_schema(main: dict[str, Any]) -> dict[str, Any]:
    """Derive the auxiliary fetcher-file schema from the ``main`` schema.

    Fetcher files may only contain the top-level ``fetching`` and ``transform`` sections. The ``fetching`` block keeps
    its full grammar (including the ``cache`` and ``mapping`` subsections); only ``MultiFetcher`` is forbidden, since it
    is permitted in the main configuration file only.
    """
    schema = deepcopy(main)
    schema["$id"] = _BASE_URL + FETCHER_FILENAME
    schema["title"] = "id-translation fetcher configuration"
    schema["description"] = (
        "Schema for id-translation auxiliary fetcher files, which may only contain the top-level `fetching` and "
        "`transform` sections. See https://id-translation.readthedocs.io/en/stable/documentation/translator-config.html"
    )
    schema["properties"] = {
        "fetching": {"$ref": "#/definitions/fetching"},
        "transform": {"$ref": "#/definitions/transform"},
    }
    # Forbid MultiFetcher in fetcher files. The key is kept in `properties` set to `false` (rejecting any value);
    # popping it would instead let the permissive `additionalProperties` accept it as a generic custom fetcher.
    schema["definitions"]["fetching"]["properties"]["MultiFetcher"] = False
    return schema


def published_schemas() -> dict[str, dict[str, Any]]:
    """Return every schema to publish, keyed by output filename."""
    main = _load(MAIN_FILENAME)
    return {
        MAIN_FILENAME: main,
        FETCHER_FILENAME: derive_fetcher_schema(main),
        METACONF_FILENAME: _load(METACONF_FILENAME),
    }
