import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Union

import pandas as pd
from rics._internal_support.types import PathLikeType
from rics.misc import get_by_full_name, tname

from ..offline.types import PlaceholderTranslations
from ..types import IdType
from ._abstract_fetcher import AbstractFetcher
from .types import FetchInstruction

LOGGER = logging.getLogger(__package__).getChild("PandasFetcher")
PandasReadFunction = Callable[[PathLikeType, Any, Any], pd.DataFrame]
FormatFn = Callable[[PathLikeType], str]


class PandasFetcher(AbstractFetcher[str, IdType]):
    """Fetcher implementation using pandas ``DataFrame`` s as the data format.

    Fetch data from serialized ``DataFrame`` s. How this is done is determined by the `read_function`. This is typically
    a Pandas function such as :func:`pandas.read_csv` or :func:`pandas.read_pickle`, but any function that accepts a
    string `source` as the  first argument and returns a data frame can be used.

    Args:
        read_function: A Pandas `read`-function.
        read_path_format: A formatting string or a callable to apply to a source before passing them to `read_function`.
            Must contain a `source` as its only placeholder. Example: ``data/{source}.pkl``. Leave as-is if ``None``.
            Valid URL schemes include http, ftp, s3, gs, and file.
        read_function_args: Additional positional arguments for `read_function`.
        read_function_kwargs: Additional keyword arguments for `read_function`.

    See Also:
        The official `Pandas IO documentation <https://pandas.pydata.org/pandas-docs/stable/user_guide/io.html>`_
    """

    def __init__(
        self,
        read_function: Union[PandasReadFunction, str] = pd.read_pickle,
        read_path_format: Union[str, FormatFn] = "data/{}.pkl",
        read_function_args: Iterable[Any] = None,
        read_function_kwargs: Mapping[str, Any] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._read = get_by_full_name(read_function, pd) if isinstance(read_function, str) else read_function
        self._format_source: FormatFn  # Oneliner makes MyPy complain?
        if callable(read_path_format):
            self._format_source = read_path_format  # pragma: no cover
        else:
            self._format_source = read_path_format.format
        self._args = read_function_args or ()
        self._kwargs = read_function_kwargs or {}

        self._source_paths: Dict[str, Path] = {}
        self._sources: List[str] = []
        self._placeholders: Dict[str, List[str]] = {}

    def read(self, source_path: PathLikeType) -> pd.DataFrame:
        """Read a ``DataFrame`` from a source path.

        Args:
            source_path: Path to serialized ``DataFrame``.

        Returns:
            A deserialized ``DataFrame``.
        """
        return self._read(source_path, *self._args, **self._kwargs)

    def find_sources(self) -> Dict[str, Path]:
        """Search for source paths to pass to `read_function` using `read_path_format`.

        Returns:
            A dict ``{source, path}``.

        Raises:
            IOError: If files cannot be read.
        """
        abs_file = Path(self._format_source("")).absolute()
        directory = abs_file.parent
        file_pattern = abs_file.name

        if not directory.is_dir():  # pragma: no cover
            problem = "is not a directory" if directory.exists() else "does not exist"
            raise IOError(f"Bad path format: {directory} {problem}.")

        source_paths = {}
        # Path.glob does not work with absolute directories.
        for file in map(Path, os.listdir(directory)):
            if file.name.endswith(str(file_pattern)):  # pragma: no cover
                source_paths[file.name.replace(file_pattern, "")] = directory.joinpath(file)

        if not source_paths:  # pragma: no cover
            pattern = Path(self._format_source("*")).absolute()
            raise IOError(f"Bad path pattern: '{pattern}' did not match any files.")

        return source_paths

    @property
    def sources(self) -> List[str]:
        if not self._sources:  # pragma: no cover
            if not self._source_paths:
                self._source_paths = self.find_sources()
            self._sources = list(self._source_paths)
            LOGGER.debug("Sources initialized: %s", self._sources)

        return self._sources

    @property
    def placeholders(self) -> Dict[str, List[str]]:
        if not self._placeholders:
            self._placeholders = {
                source: list(self.read(self._source_paths[source]).columns) for source in self.sources
            }

        return self._placeholders

    def fetch_translations(self, instr: FetchInstruction[str, IdType]) -> PlaceholderTranslations[str]:
        return PlaceholderTranslations.make(
            instr.source,
            self.read(self._source_paths[instr.source]),
        )

    def __repr__(self) -> str:
        read_path_format = self._format_source("{source}")
        return f"{tname(self)}(read_function={tname(self._read)}, {read_path_format=})"
