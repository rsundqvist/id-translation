import tomllib
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from rics.env.interpolation import UnsetVariableError, replace_in_string
from rics.paths import AnyPath, any_path_to_path

from id_translation._utils import add_hints

from .exceptions import ConfigFileError


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
        ~id_translation.toml.exceptions.ConfigFileError: If the file is not UTF-8 or not valid TOML, or its
            interpolation syntax is malformed. The original error is the cause.
        rics.env.interpolation.UnsetVariableError: If a required environment variable is unset, or blank and
            ``allow_blank=False``. A hint names the file.
        OSError: If the file cannot be read, e.g. :class:`FileNotFoundError`.
    """
    path = any_path_to_path(path)
    data = path.read_bytes()
    hint = f"In file: {path.resolve()}"

    try:
        toml_string = data.decode("UTF-8")
        if allow_interpolation:
            toml_string = replace_in_string(toml_string, allow_nested=allow_nested, allow_blank=allow_blank)
        return tomllib.loads(toml_string)
    except UnsetVariableError as e:
        add_hints(e, hint)  # The environment's, not the file's: the variable is named, and the file may be fine.
        raise
    except (ValueError, NotImplementedError) as e:
        # A UnicodeDecodeError or TOMLDecodeError, or rics rejecting the interpolation syntax: a ValueError for a nested
        # variable when allow_nested=False, a NotImplementedError for a nested default it cannot resolve.
        raise ConfigFileError(f"{type(e).__name__}: {e}", hints=hint) from e


@contextmanager
def _rethrow_with_file(file: AnyPath) -> Generator[None, None, None]:
    hint = f"In file: {any_path_to_path(file).resolve()}"
    try:
        yield
    except Exception as e:
        if f"Hint: {hint}" not in getattr(e, "__notes__", ()):  # load_toml_file() may have named it already.
            add_hints(e, hint)
        raise
