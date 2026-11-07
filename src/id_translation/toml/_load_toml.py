import tomllib
from typing import Any

from rics.env.interpolation import replace_in_string
from rics.paths import AnyPath, any_path_to_path

from id_translation.exceptions import ConfigurationError


def load_toml_file(
    path: AnyPath,
    *,
    allow_interpolation: bool = False,
    allow_nested: bool = False,
    allow_blank: bool = False,
) -> dict[str, Any]:
    """Load a TOML file.

    This function reads a TOML file with forced `UTF-8` encoding (as per the standard). It will optionally perform
    environment variable value interpolation as well and replace matching names in the file (in-memory, the file will
    not be changed or read more than once).

    For details about the interpolation, see :func:`rics.env.interpolation.replace_in_string`.

    Args:
        path: Path to file.
        allow_interpolation: If ``True``, perform env var value interpolation.
        allow_blank: If ``False``, blank values are considered missing.
        allow_nested: If ``False``, raise an error if variables are defined within the default value of other variables.

    Returns:
        A dict parsed from `path`.

    Raises:
        ConfigurationError: If the file is not valid TOML, or interpolation fails. The original error is the cause.
        OSError: If the file cannot be read, e.g. :class:`FileNotFoundError`.
    """
    path = any_path_to_path(path)
    data = path.read_bytes()

    try:
        toml_string = data.decode("UTF-8")
        if allow_interpolation:
            toml_string = replace_in_string(toml_string, allow_nested=allow_nested, allow_blank=allow_blank)
        return tomllib.loads(toml_string)
    except Exception as e:
        # One exception type for any problem with the content; a missing file is the environment's, and stays OSError.
        raise ConfigurationError(f"{type(e).__name__}: {e}", hints=f"In file: {path.resolve()}") from e
