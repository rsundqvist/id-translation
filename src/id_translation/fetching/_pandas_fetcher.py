import logging
from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path
from typing import Any, Unpack

import pandas as pd
from rics.misc import get_by_full_name, tname
from rics.types import AnyPath

from ..logging import generate_task_id
from ..offline.types import PlaceholderTranslations
from ..types import IdType
from ._abstract_fetcher import AbstractFetcher, AbstractFetcherParams
from .types import FetchInstruction

PandasReadFunction = Callable[[AnyPath], pd.DataFrame]
FormatFn = Callable[[str], str]

# Suffixes are matched longest first, so `.jsonl` wins over `.json`.
_SUFFIX_TO_READER: dict[str, tuple[str, PandasReadFunction]] = {
    ".csv": ("pandas.read_csv", pd.read_csv),
    ".json": ("pandas.read_json", pd.read_json),
    ".jsonl": ("pandas.read_json(lines=True)", partial(pd.read_json, lines=True)),
    ".ndjson": ("pandas.read_json(lines=True)", partial(pd.read_json, lines=True)),
    ".parquet": ("pandas.read_parquet", pd.read_parquet),
    ".parq": ("pandas.read_parquet", pd.read_parquet),
    ".pq": ("pandas.read_parquet", pd.read_parquet),
    ".feather": ("pandas.read_feather", pd.read_feather),
    ".ftr": ("pandas.read_feather", pd.read_feather),
    ".arrow": ("pandas.read_feather", pd.read_feather),
    ".orc": ("pandas.read_orc", pd.read_orc),
    ".pickle": ("pandas.read_pickle", pd.read_pickle),
    ".pkl": ("pandas.read_pickle", pd.read_pickle),
    ".xlsx": ("pandas.read_excel", pd.read_excel),
    ".xlsm": ("pandas.read_excel", pd.read_excel),
    ".xls": ("pandas.read_excel", pd.read_excel),
    ".ods": ("pandas.read_excel", pd.read_excel),
}


class PandasFetcher(AbstractFetcher[str, IdType]):
    """Fetcher implementation using :class:`pandas.DataFrame` as the data format.

    Fetch data from serialized frames. How this is done is determined by the `read_function`. This is typically a Pandas
    function such as :func:`pandas.read_csv` or :func:`pandas.read_parquet`, but any function that accepts a string
    `source` as the first argument and returns a :class:`pandas.DataFrame` can be used.

    When `read_function` is ``None``, it is derived from a suffix in the file name part of `read_path_format`. The
    suffix may appear anywhere in the file name, so ``'{}.csv.zip'`` is read with :func:`pandas.read_csv`.

    * ``.csv``: :func:`pandas.read_csv`.
    * ``.json``: :func:`pandas.read_json`; ``.jsonl``, ``.ndjson``: :func:`pandas.read_json` with ``lines=True``.
    * ``.parquet``, ``.parq``, ``.pq``: :func:`pandas.read_parquet`.
    * ``.feather``, ``.ftr``, ``.arrow``: :func:`pandas.read_feather`.
    * ``.orc``: :func:`pandas.read_orc`.
    * ``.pickle``, ``.pkl``: :func:`pandas.read_pickle`.
    * ``.xlsx``, ``.xlsm``, ``.xls``, ``.ods``: :func:`pandas.read_excel`.

    .. hint::

       When using **remote file systems**, :attr:`~id_translation.fetching.AbstractFetcher.sources` are resolved using
       `AbstractFileSystem.glob()`_. If resolution fails, consider overriding the
       :meth:`~id_translation.fetching.PandasFetcher.find_sources`-method.

    Args:
        read_path_format: A string on the form ``protocol://path/to/sources/{}.<ext>``, or a callable to apply to a
            source before passing them to `read_function`. Every matching file is a source.
        read_function: A function ``(str) -> DataFrame``. Derive from `read_path_format` if ``None``. Strings are
            resolved by :func:`~rics.misc.get_by_full_name` (with ``default_module=pandas``).
        read_function_kwargs: Additional keyword arguments for `read_function`.
        **kwargs: See :class:`~id_translation.fetching.AbstractFetcher`.

    See Also:
        The official `Pandas IO documentation <https://pandas.pydata.org/pandas-docs/stable/user_guide/io.html>`_

    .. _AbstractFileSystem.glob(): https://filesystem-spec.readthedocs.io/en/latest/api.html?highlight=glob#fsspec.spec.AbstractFileSystem.glob
    """

    def __init__(
        self,
        read_path_format: str | FormatFn = "data/{}.csv",
        *,
        read_function: PandasReadFunction | str | None = None,
        read_function_kwargs: Mapping[str, Any] | None = None,
        **kwargs: Unpack[AbstractFetcherParams[str, IdType]],
    ) -> None:
        super().__init__(**kwargs)

        self._read_name, self._read = self._derive_read_function(read_function, read_path_format)
        self._format_source: FormatFn = read_path_format if callable(read_path_format) else read_path_format.format
        self._kwargs = read_function_kwargs or {}

        self._source_paths: dict[str, str] = {}

    def read(self, source_path: AnyPath) -> pd.DataFrame:
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

    def find_sources(self, task_id: int | None = None) -> dict[str, str]:
        """Resolve sources and their associated paths.

        Args:
            task_id: Used for logging.

        Sources are resolved in three steps:

        1. Create glob pattern by calling :meth:`~id_translation.fetching.PandasFetcher.format_source` with ``source='*'``.
        2. Glob files using `AbstractFileSystem.glob()`_ (requires ``fsspec``) or :meth:`Path.glob() <pathlib.Path.glob>`.
        3. Strip the directory and file suffix from the globbed paths to create source names.

        .. _AbstractFileSystem.glob(): https://filesystem-spec.readthedocs.io/en/latest/api.html?highlight=glob#fsspec.spec.AbstractFileSystem.glob

        Returns:
            A dict ``{source: path}``.
        """
        if task_id is None:
            task_id = generate_task_id()

        pattern = self.format_source("*")

        try:
            sources = self._find_sources_fsspec(pattern)
        except ModuleNotFoundError as e:
            self.logger.debug(f"Falling back to 'pathlib.Path': {e!r}")
            sources = self._find_sources_pathlib(Path(pattern).expanduser().resolve())

        source_paths: dict[str, str] = {source: self.format_source(source) for source in sources}

        extra = {"task_id": task_id, "pattern": pattern, "source_paths": source_paths}
        if not source_paths:
            self.logger.warning(f"Path {pattern=} did not match any files.", extra=extra)
            return {}

        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(f"Path {pattern=} matched {len(source_paths)} files: {source_paths}", extra=extra)

        return source_paths

    def _find_sources_fsspec(self, pattern: str) -> list[str]:
        from fsspec.core import url_to_fs  # type: ignore  # noqa: PLC0415

        fs, pattern = url_to_fs(pattern, **self._kwargs.get("storage_options", {}))
        return [self._path_to_source(path, pattern) for path in fs.glob(pattern)]

    @classmethod
    def _find_sources_pathlib(cls, pattern: Path) -> list[str]:
        return [cls._path_to_source(str(path), str(pattern)) for path in pattern.parent.glob(pattern.name)]

    @classmethod
    def _path_to_source(cls, path: str, pattern: str) -> str:
        glob_index = pattern.index("*")
        prefix = pattern[:glob_index]
        suffix = pattern[glob_index + 1 :]
        return path.removeprefix(prefix).removesuffix(suffix)

    def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:
        self._source_paths = self.find_sources(task_id)
        return {source: self.read(path).columns.tolist() for source, path in self._source_paths.items()}

    def fetch_translations(self, instr: FetchInstruction[str, IdType]) -> PlaceholderTranslations[str]:
        """Fetch translations from a filesystem source."""
        return PlaceholderTranslations.make(
            instr.source,
            self.read(self._source_paths[instr.source]),
        )

    def __repr__(self) -> str:
        read_path_format = self.format_source("{}")
        return f"{tname(self)}(read_function={self._read_name}, {read_path_format=})"

    def _derive_read_function(
        self,
        read_function: PandasReadFunction | str | None,
        read_path_format: str | FormatFn,
    ) -> tuple[str, PandasReadFunction]:
        if callable(read_function):
            return tname(read_function), read_function

        if read_function is None:
            if not isinstance(read_path_format, str):
                msg = (
                    f"Cannot derive `read_function` from {read_path_format=} of type={type(read_path_format).__name__}."
                )
                raise ValueError(msg)

            # Search only the file name after the placeholder, ignoring directories such as `.parquet-cache/`.
            file_name = read_path_format.rpartition("{}")[2].rstrip("/").rpartition("/")[2]
            for suffix in sorted(_SUFFIX_TO_READER, key=len, reverse=True):
                if suffix in file_name:  # Using endswith would break paths such as .csv.zip
                    name, func = _SUFFIX_TO_READER[suffix]
                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug(
                            f"Derived read_function={name!r} based on {suffix=} found in {read_path_format=}.",
                            extra={"suffix": suffix, "read_function": name},
                        )
                    return name, func

            suffixes = list(_SUFFIX_TO_READER)
            msg = f"Cannot derive `read_function` from {read_path_format=}; {file_name=} has no known {suffixes=}."
            raise ValueError(msg)

        func = get_by_full_name(read_function, pd)
        if not callable(func):
            msg = f"Bad {read_function=}; type {type(func).__name__} is not callable."
            raise TypeError(msg)
        return read_function, func
