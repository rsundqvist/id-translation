import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Unpack

import pandas as pd
from rics.misc import get_by_full_name, tname
from rics.types import AnyPath

from ..logging import generate_task_id
from ..offline.types import PlaceholderTranslations
from ..translator_typing import AbstractFetcherParams
from ..types import IdType
from ._abstract_fetcher import AbstractFetcher
from .types import FetchInstruction

PandasReadFunction = Callable[[AnyPath], pd.DataFrame]
FormatFn = Callable[[str], str]


class PandasFetcher(AbstractFetcher[str, IdType]):
    """Fetcher implementation using :class:`pandas.DataFrame` as the data format.

    Fetch data from serialized frames. How this is done is determined by the `read_function`. This is typically a Pandas
    function such as :func:`pandas.read_csv` or :func:`pandas.read_parquet`, but any function that accepts a string
    `source` as the first argument and returns a :class:`pandas.DataFrame` can be used.

    .. hint::

       When using **remote file systems**, :attr:`~.AbstractFetcher.sources` are resolved using
       `AbstractFileSystem.glob()`_. If resolution fails, consider overriding the :meth:`find_sources`-method.

    Args:
        read_function: A function ``(str) -> DataFrame``. Derive from `read_path_format` if ``None``. Strings are
            resolved by :func:`~rics.misc.get_by_full_name` (with ``default_module=pandas``).
        read_path_format: A string on the form ``protocol://path/to/sources/{}.<ext>``, or a callable to apply
            to a source before passing them to `read_function`.
        read_function_kwargs: Additional keyword arguments for `read_function`.
        **kwargs: See :class:`.AbstractFetcher`.

    See Also:
        The official `Pandas IO documentation <https://pandas.pydata.org/pandas-docs/stable/user_guide/io.html>`_

    .. _AbstractFileSystem.glob(): https://filesystem-spec.readthedocs.io/en/latest/api.html?highlight=glob#fsspec.spec.AbstractFileSystem.glob
    """

    def __init__(
        self,
        read_function: PandasReadFunction | str | None = None,
        read_path_format: str | FormatFn = "data/{}.csv",
        read_function_kwargs: Mapping[str, Any] | None = None,
        **kwargs: Unpack[AbstractFetcherParams[str, IdType]],
    ) -> None:
        super().__init__(**kwargs)

        self._read = self._derive_read_function(read_function, read_path_format)
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

        1. Create glob pattern by calling :meth:`format_source` with ``source='*'``.
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
            self.logger.debug("Falling back to 'pathlib.Path': %r", e)
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
        return PlaceholderTranslations.make(
            instr.source,
            self.read(self._source_paths[instr.source]),
        )

    def __repr__(self) -> str:
        read_path_format = self.format_source("{}")
        return f"{tname(self)}(read_function={tname(self._read)}, {read_path_format=})"

    def _derive_read_function(
        self,
        read_function: PandasReadFunction | str | None,
        read_path_format: str | FormatFn,
    ) -> PandasReadFunction:
        if callable(read_function):
            return read_function

        if read_function is None:
            if not isinstance(read_path_format, str):
                msg = f"Cannot derive `read_function` from {read_path_format=} of type={type(read_function)}."
                raise ValueError(msg)

            func_to_suffixes: dict[PandasReadFunction, list[str]] = {
                pd.read_csv: [".csv"],
                pd.read_pickle: [".pickle", ".pkl"],
                pd.read_feather: [".feather", ".ftr"],
                pd.read_json: [".json"],
                pd.read_parquet: [".parquet", ".parq"],
            }

            for func, suffixes in func_to_suffixes.items():
                for suffix in suffixes:
                    if suffix in read_path_format:  # Using endswith would break paths such as .csv.zip
                        if self.logger.isEnabledFor(logging.INFO):
                            read_function = f"pandas.{func.__name__}"
                            self.logger.debug(
                                f"Derived {read_function=} based on {suffix=} found in {read_path_format=}.",
                                extra={"suffix": suffix, "read_function": read_function},
                            )
                        return func

            suffixes = [suffix for suffixes in func_to_suffixes.values() for suffix in suffixes]
            msg = f"Cannot derive `read_function` from {read_path_format=}; does not contain any known {suffixes=}."
            raise ValueError(msg)

        func = get_by_full_name(read_function, pd)
        if not callable(func):
            msg = f"Bad {read_function=}; type {type(func).__name__} is not callable."
            raise TypeError(msg)
        return func  # type: ignore[no-any-return]
