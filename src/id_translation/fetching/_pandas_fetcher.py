from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd
from rics._internal_support.types import PathLikeType
from rics.misc import get_by_full_name, tname

from ..offline.types import PlaceholderTranslations
from ..types import IdType
from ._abstract_fetcher import AbstractFetcher
from .types import FetchInstruction

PandasReadFunction = Callable[[str], pd.DataFrame]
FormatFn = Callable[[str], str]


class PandasFetcher(AbstractFetcher[str, IdType]):
    """Fetcher implementation using pandas ``DataFrame`` s as the data format.

    Fetch data from serialized ``DataFrame`` s. How this is done is determined by the `read_function`. This is typically
    a Pandas function such as :func:`pandas.read_csv` or :func:`pandas.read_parquet`, but any function that accepts a
    string `source` as the  first argument and returns a data frame can be used.

    .. hint::

       When using **remote file systems**, :attr:`~.AbstractFetcher.sources` are resolved using
       `AbstractFileSystem.glob()`_. If resolution fails, consider overriding the :meth:`find_sources`-method.

    Args:
        read_function: A Pandas `read`-function. If a string is given, the function is resolved using
            :func:`rics.misc.get_by_full_name`. Unqualified names are assumed to belong to the ``pandas`` namespace.
        read_path_format: A string on the form ``protocol://path/to/sources/{}.ext``, or a callable to apply
            to a source before passing them to `read_function`.
        read_function_kwargs: Additional keyword arguments for `read_function`.
        online: Setting ``online=False`` typically indicates that files are hosted at a location where there are access
            limitations, e.g. through data transfer fees.

    See Also:
        The official `Pandas IO documentation <https://pandas.pydata.org/pandas-docs/stable/user_guide/io.html>`_

    .. _AbstractFileSystem.glob(): https://filesystem-spec.readthedocs.io/en/latest/api.html?highlight=glob#fsspec.spec.AbstractFileSystem.glob
    """

    def __init__(
        self,
        read_function: PandasReadFunction | str = "read_csv",
        read_path_format: str | FormatFn = "data/{}.csv",
        read_function_kwargs: Mapping[str, Any] | None = None,
        online: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._read = get_by_full_name(read_function, pd) if isinstance(read_function, str) else read_function
        self._format_source: FormatFn  # Oneliner makes MyPy complain?
        if callable(read_path_format):
            self._format_source = read_path_format  # pragma: no cover
        else:
            self._format_source = read_path_format.format
        self._online = online
        self._kwargs = read_function_kwargs or {}

        self._source_paths: dict[str, str] = {}

    def read(self, source_path: PathLikeType) -> pd.DataFrame:
        """Read a ``DataFrame`` from a source path.

        Args:
            source_path: Path to serialized ``DataFrame``.

        Returns:
            A deserialized ``DataFrame``.
        """
        return self._read(source_path, **self._kwargs).convert_dtypes()

    def format_source(self, source: str) -> str:
        """Get the path for `source`."""
        return self._format_source(source)

    def find_sources(self, task_id: int = -1) -> dict[str, str]:
        """Resolve sources and their associated paths.

        Args:
            task_id: Used for logging.

        Sources are resolved in three steps:

        1. Create glob pattern by calling :meth:`format_source` with ``source='*'``.
        2. Glob files using `AbstractFileSystem.glob()`_ (requires ``fsspec``) or :meth:`Path.glob() <pathlib.Path.glob>`.
        3. Strip the directory  and file suffix from the globbed paths to create source names.

        .. _AbstractFileSystem.glob(): https://filesystem-spec.readthedocs.io/en/latest/api.html?highlight=glob#fsspec.spec.AbstractFileSystem.glob

        Returns:
            A dict ``{source: path}``.
        """
        pattern = self.format_source("*")

        try:
            source_paths = self._find_sources_fsspec(pattern)
        except ModuleNotFoundError as e:
            self.logger.debug(f"Falling back to 'pathlib.Path': {e!r}")
            source_paths = self._find_sources_pathlib(pattern)

        extra = {"task_id": task_id, "pattern": pattern}
        if source_paths:
            self.logger.debug(f"Path {pattern=} matched {len(source_paths)} files: {source_paths}", extra=extra)
            return source_paths
        else:
            self.logger.warning(f"Path {pattern=} did not match any files.", extra=extra)
            return {}

    def _find_sources_fsspec(self, pattern: str) -> dict[str, str]:
        from fsspec.core import url_to_fs  # type: ignore

        fs, _ = url_to_fs(pattern, **self._kwargs.get("storage_options", {}))

        source_paths = self._make_source_paths(fs.glob(pattern))

        protocol, separator, _ = pattern.partition("://")
        if separator:
            source_paths = {source: protocol + separator + path for source, path in source_paths.items()}

        return source_paths

    def _find_sources_pathlib(self, pattern: str) -> dict[str, str]:
        path = Path(pattern)
        iterator = path.parent.glob(path.name)
        return self._make_source_paths(iterator)

    @staticmethod
    def _make_source_paths(iterator: Iterable[Path]) -> dict[str, str]:
        source_paths = {}
        for path in map(Path, iterator):
            source = path.with_suffix("").name
            source_paths[source] = str(path)
        return source_paths

    def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:
        self._source_paths = self.find_sources(task_id)
        return {source: self.read(path).columns.tolist() for source, path in self._source_paths.items()}

    def fetch_translations(self, instr: FetchInstruction[str, IdType]) -> PlaceholderTranslations[str]:
        return PlaceholderTranslations.make(
            instr.source,
            self.read(self._source_paths[instr.source]),
        )

    @property
    def online(self) -> bool:
        return self._online

    def __repr__(self) -> str:
        read_path_format = self.format_source("{}")
        return f"{tname(self)}(read_function={tname(self._read)}, {read_path_format=})"
