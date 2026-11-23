import logging
import ntpath
from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path
from typing import Any, Unpack

import pandas as pd
from rics.misc import get_by_full_name, tname
from rics.types import AnyPath

from .. import _uuid_utils
from .._utils import add_hints, require_bool
from ..logging import generate_task_id
from ..offline.types import PlaceholderTranslations
from ..types import ID, IdType
from . import exceptions
from ._abstract_fetcher import AbstractFetcher, AbstractFetcherParams
from .types import FetchInstruction

PandasReadFunction = Callable[[AnyPath], pd.DataFrame]
FormatFn = Callable[[str], str]

_READ_FUNCTION_HINT = "Set `read_function`, e.g. `'read_csv'`."
_PLACEHOLDER_HINT = "Put `{}` where the source name goes, e.g. `'data/{}.csv'`."

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

    Fetch data from serialized frames. A `read_function` ``(str) -> pandas.DataFrame`` reads each source from the path
    that `read_path_format` gives it. When `read_function` is ``None``, it is derived from the file name in
    `read_path_format`, using the table below:

    ========================================  ============================================
    Suffix                                    Reader
    ========================================  ============================================
    ``.csv``                                  :func:`pandas.read_csv`
    ``.json``                                 :func:`pandas.read_json`
    ``.jsonl``, ``.ndjson``                   :func:`pandas.read_json` with ``lines=True``
    ``.parquet``, ``.parq``, ``.pq``          :func:`pandas.read_parquet`
    ``.feather``, ``.ftr``, ``.arrow``        :func:`pandas.read_feather`
    ``.orc``                                  :func:`pandas.read_orc`
    ``.pickle``, ``.pkl``                     :func:`pandas.read_pickle`
    ``.xlsx``, ``.xlsm``, ``.xls``, ``.ods``  :func:`pandas.read_excel`
    ========================================  ============================================

    .. hint::

       When using **remote file systems**, :attr:`~id_translation.fetching.AbstractFetcher.sources` are resolved using
       `AbstractFileSystem.glob()`_. If resolution fails, consider overriding the
       :meth:`~id_translation.fetching.PandasFetcher.find_sources`-method.

    Args:
        read_path_format: A string on the form ``protocol://path/to/sources/{}.<ext>``, or a callable to apply to a
            source before passing it to `read_function`. Every matching file is a source.
        read_function: A function ``(str) -> DataFrame``. Derive from `read_path_format` if ``None``. Strings are
            resolved by :func:`~rics.misc.get_by_full_name` (with ``default_module=pandas``).
        read_function_kwargs: Additional keyword arguments for `read_function`.
        return_all: If ``True``, return every ID and placeholder of a source instead of only the requested ones.
            Translations then include IDs that were not asked for, e.g. as extra categories when translating to a
            categorical ``dtype``.
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
        return_all: bool = False,
        **kwargs: Unpack[AbstractFetcherParams[str, IdType]],
    ) -> None:
        require_bool(return_all=return_all)
        super().__init__(**kwargs)

        self._check_read_path_format(read_path_format, read_function)
        self._read_name, self._read = self._derive_read_function(read_function, read_path_format)
        self._format_source: FormatFn = read_path_format if callable(read_path_format) else read_path_format.format
        self._kwargs = read_function_kwargs or {}

        self._source_paths: dict[str, str] = {}
        self._id_columns: dict[str, str] = {}
        self._return_all = return_all

    @property
    def return_all(self) -> bool:
        """If ``True``, return all data instead of only the requested IDs and placeholders."""
        return self._return_all

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
        if not _globs_by_source(self.format_source):
            msg = f"Cannot find sources: format_source('*') returned {pattern!r}, which does not glob by source name."
            exc = ValueError(msg)
            add_hints(exc, "Return a glob pattern from format_source('*'), or override find_sources().")
            raise exc

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
        placeholders = {source: self.read(path).columns.tolist() for source, path in self._source_paths.items()}

        for source, columns in placeholders.items():
            id_column = self.id_column(source, candidates=columns, task_id=task_id)
            if id_column is None:
                raise exceptions.UnknownPlaceholderError.for_placeholders(
                    ID,
                    placeholders=columns,
                    source=source,
                    caller=self,
                    hints=[
                        self._missing_id_column_hint(source),
                        f"If {self._source_paths[source]!r} is not a source, change"
                        f" read_path_format={self.format_source('{}')!r} so that it does not match.",
                    ],
                )
            self._id_columns[source] = id_column

        return placeholders

    def fetch_translations(self, instr: FetchInstruction[str, IdType]) -> PlaceholderTranslations[str]:
        """Fetch translations from a filesystem source."""
        df = self.read(self._source_paths[instr.source])

        if self.return_all:
            return PlaceholderTranslations.make(instr.source, df)

        if instr.ids is not None:
            ids = df[self._id_columns[instr.source]]
            keep = ids.isin(instr.ids).to_numpy(dtype=bool, na_value=False)
            if instr.enable_uuid_heuristics:
                # Both forms: requested IDs are cast only when every one of them is UUID-like.
                cast = ids.map(_uuid_utils.try_cast_one)
                keep = keep | cast.isin(instr.ids).to_numpy(dtype=bool, na_value=False)
            df = df[keep]

        df = df[[column for column in dict.fromkeys(instr.placeholders) if column in df.columns]]

        return PlaceholderTranslations.make(instr.source, df)

    def __repr__(self) -> str:
        read_path_format = self.format_source("{}")
        return_all = self.return_all
        return f"{tname(self)}(read_function={self._read_name}, {read_path_format=}, {return_all=})"

    def _check_read_path_format(
        self,
        read_path_format: str | FormatFn,
        read_function: PandasReadFunction | str | None,
    ) -> None:
        """Fail at construction for a format that the default ``format_source()`` and ``find_sources()`` cannot use."""
        if not isinstance(read_path_format, str) or type(self).format_source is not PandasFetcher.format_source:
            return

        try:
            globs = _globs_by_source(read_path_format.format)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as e:  # What str.format() raises.
            exc = ValueError(f"Bad {read_path_format=}: {e!r}; it is formatted with the source name alone.")
            add_hints(exc, _PLACEHOLDER_HINT)
            raise exc from e

        if globs or type(self).find_sources is not PandasFetcher.find_sources:
            return  # Own discovery may use a fixed path.

        # E.g. a fixed path, or a 1.x read function name such as 'pandas.io.json.read_json'.
        what = "derive `read_function` from" if read_function is None else "use"
        exc = ValueError(f"Cannot {what} {read_path_format=}; it has no placeholder for the source.")
        add_hints(exc, [_PLACEHOLDER_HINT, _READ_FUNCTION_HINT] if read_function is None else _PLACEHOLDER_HINT)
        raise exc

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
                exc = ValueError(msg)
                if callable(read_path_format):  # A `Path` cannot be helped by a read function.
                    add_hints(exc, _READ_FUNCTION_HINT)
                raise exc

            # Only the file name: directories such as `.parquet-cache/` don't count. ntpath splits on both / and \.
            file_name = ntpath.basename(read_path_format.rstrip("/\\"))
            for part in reversed(file_name.split(".")[1:]):  # The last known suffix wins: `.parquet.csv` is a CSV.
                if (suffix := f".{part}") in _SUFFIX_TO_READER:
                    name, func = _SUFFIX_TO_READER[suffix]
                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug(
                            f"Derived read_function={name!r} based on {suffix=} found in {read_path_format=}.",
                            extra={"suffix": suffix, "read_function": name},
                        )
                    return name, func

            suffixes = list(_SUFFIX_TO_READER)
            msg = f"Cannot derive `read_function` from {read_path_format=}; {file_name=} has no known {suffixes=}."
            exc = ValueError(msg)
            add_hints(exc, _READ_FUNCTION_HINT)
            raise exc

        func = get_by_full_name(read_function, pd)
        if not callable(func):
            msg = f"Bad {read_function=}; type {type(func).__name__} is not callable."
            raise TypeError(msg)
        return read_function, func


def _globs_by_source(format_source: FormatFn) -> bool:
    """Return whether ``format_source('*')`` is a glob and the path depends on the source, as the default discovery needs.

    A literal ``*`` alone passes the first test: ``'data/*.csv'`` globs, but gives every source the same path.
    """
    pattern = format_source("*")
    return "*" in pattern and pattern != format_source("_")
