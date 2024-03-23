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
"""

from ._abstract_fetcher import AbstractFetcher
from ._cache import CacheAccess, CacheMetadata
from ._fetcher import Fetcher
from ._memory_fetcher import MemoryFetcher
from ._multi_fetcher import MultiFetcher
from ._pandas_fetcher import PandasFetcher
from ._sql_fetcher import SqlFetcher

__all__ = [
    "Fetcher",
    "AbstractFetcher",
    "CacheAccess",
    "CacheMetadata",
    "MemoryFetcher",
    "MultiFetcher",
    "PandasFetcher",
    "SqlFetcher",
]
