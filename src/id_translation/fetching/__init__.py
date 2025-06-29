"""Fetching of translation data.

Composite:
    * :class:`.MultiFetcher`: Solution for using multiple simple fetchers, e.g. multiple databases or file-system
      locations. Or a combination thereof!

Simple fetchers:
    * :class:`.SqlFetcher`: Fetching from a single SQL database or schema.
    * :class:`.PandasFetcher`: File-system fetching based on pandas read-functions. Valid URL schemes include http, ftp,
      s3, gs, and file.
    * :class:`.MemoryFetcher`: In-memory solution, used primarily for testing.

Base fetchers:
    * :class:`.Fetcher`: Top-level interface definition. Base for all fetching implementations.
    * :class:`.AbstractFetcher`: Implements high-level operations such as
      `placeholder mapping <../documentation/translation-primer.html#placeholder-mapping>`__.

Fetchers may have additional dependencies.
"""

from ._abstract_fetcher import AbstractFetcher
from ._cache_access import CacheAccess
from ._fetcher import Fetcher
from ._memory_fetcher import MemoryFetcher
from ._multi_fetcher import MultiFetcher


def _missing_dependency(name, cls):  # type: ignore  # noqa
    class MissingDependency(AbstractFetcher):  # type: ignore
        def _initialize_sources(self, task_id): ...  # type: ignore  # noqa
        def fetch_translations(self, instr): ...  # type: ignore  # noqa
        def __init__(self, *args, **kwargs):  # type: ignore  # noqa
            raise ImportError(f"Install `{name}` or `id-translation[fetching]` to use {cls}.") from None

    return MissingDependency


try:
    from ._pandas_fetcher import PandasFetcher
except ImportError as e:
    PandasFetcher = _missing_dependency(e.name, "PandasFetcher")  # type: ignore


try:
    from ._sql_fetcher import SqlFetcher
except ImportError as e:
    SqlFetcher = _missing_dependency(e.name, "SqlFetcher")  # type: ignore

__all__ = [
    "AbstractFetcher",
    "CacheAccess",
    "Fetcher",
    "MemoryFetcher",
    "MultiFetcher",
    "PandasFetcher",
    "SqlFetcher",
]
