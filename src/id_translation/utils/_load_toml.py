from pathlib import Path
from typing import Any

import tomllib
from rics._internal_support.types import PathLikeType
from rics.misc import interpolate_environment_variables


def load_toml_file(
    path: PathLikeType,
    *,
    allow_interpolation: bool = False,
    allow_nested: bool = False,
    allow_blank: bool = False,
) -> dict[str, Any]:
    """Load a TOML file.

    This function reads a TOML file with forced `UTF-8` encoding (as per the standard). It will optionally perform
    environment variable value interpolation as well and replace matching names in the file (in-memory, the file will
    not be changed or read more than once).

    For details about the interpolation, see :func:`rics.misc.interpolate_environment_variables`.

    Args:
        path: Path to file.
        allow_interpolation: If ``True``, perform env var value interpolation.
        allow_blank: If ``False``, blank values are considered missing.
        allow_nested: If ``False``, raise an error if variables are defined within the default value of other variables.

    Returns:
        A dict parsed from `path`.
    """
    with Path(path).open(encoding="UTF-8") as f:
        toml_string = f.read()

    if allow_interpolation:
        toml_string = interpolate_environment_variables(toml_string, allow_nested=allow_nested, allow_blank=allow_blank)

    return tomllib.loads(toml_string)
