"""An in-memory CacheAccess example.

Downloaded from:
    https://id-translation.readthedocs.io/en/stable/documentation/examples/caching/in_memory.html

This implementation provides:
    * Per-ID translations held in process memory (no disk, no pickle).
    * Incremental caching: only the IDs that are actually translated are kept.
    * A per-ID time-to-live (TTL) in seconds, and a per-source size cap.

Reach for this instead of Translator.load_persistent_instance() when you want
caching but cannot accept its pickle dependency, and want to stay online so new
IDs are fetched on demand. Unlike the on-disk example -- which caches whole
fetch_all tables -- this accumulates the "hot" subset of IDs across by-ID
translate() calls, which is what an online service typically does.

Two things worth understanding:

* The CacheAccess contract is all-or-nothing: load() must return translations
  that fully cover the request, or None. There is no partial hit, so we return a
  cache entry only when *every* requested ID is present and unexpired; otherwise
  we return None and let the fetcher re-fetch (and re-cache) the whole request.
* Simplification -- a source is assumed to always be fetched with the same
  placeholders. We store one row per ID for the most recent placeholder layout
  and reset a source's cache if its placeholders change. A production cache that
  mixes placeholder sets per source would instead key rows by placeholder layout
  and verify coverage in load().
"""

import time
from dataclasses import dataclass

from id_translation.fetching import CacheAccess
from id_translation.fetching.types import FetchInstruction
from id_translation.offline.types import PlaceholdersTuple, PlaceholderTranslations
from id_translation.types import IdType, SourceType


@dataclass
class _SourceCache:
    placeholders: PlaceholdersTuple
    id_pos: int
    aliases: dict[str, str]
    rows: dict  # id -> (stored_at, row)


class InMemoryCacheAccess(CacheAccess[SourceType, IdType]):
    """Per-ID, in-process caching with a TTL and a per-source size cap."""

    def __init__(self, ttl: float, max_ids: int = 100_000) -> None:
        super().__init__()
        self._ttl = ttl  # In seconds.
        self._max_ids = max_ids
        self._cache: dict[SourceType, _SourceCache] = {}

    def store(
        self,
        instr: FetchInstruction[SourceType, IdType],
        translations: PlaceholderTranslations[SourceType],
    ) -> None:
        source = translations.source
        sc = self._cache.get(source)
        if sc is None or sc.placeholders != translations.placeholders:
            # New source, or the placeholder layout changed (see
            # module docstring): start fresh.
            sc = _SourceCache(
                translations.placeholders,
                translations.id_pos,
                aliases=dict(translations.placeholder_aliases),
                rows={},
            )
            self._cache[source] = sc

        now = time.monotonic()
        id_pos = translations.id_pos
        for row in translations.records:
            sc.rows[row[id_pos]] = (now, tuple(row))

        self._evict(sc)

    def load(
        self,
        instr: FetchInstruction[SourceType, IdType],
    ) -> PlaceholderTranslations[SourceType] | None:
        if instr.ids is None:
            return None  # An accumulated cache cannot prove it holds *all* IDs (fetch_all).

        sc = self._cache.get(instr.source)
        if sc is None:
            return None

        deadline = time.monotonic() - self._ttl
        records = []
        for id_ in instr.ids:
            entry = sc.rows.get(id_)
            if entry is None or entry[0] < deadline:
                return None  # Missing or expired: not a full hit (all-or-nothing).
            records.append(entry[1])

        return PlaceholderTranslations(
            source=instr.source,
            placeholders=sc.placeholders,
            records=records,
            id_pos=sc.id_pos,
            placeholder_aliases=dict(sc.aliases),
        )

    def _evict(self, sc: _SourceCache) -> None:
        # Drop the oldest entries once the per-source cap is exceeded.
        excess = len(sc.rows) - self._max_ids
        if excess > 0:
            for id_ in sorted(sc.rows, key=lambda i: sc.rows[i][0])[:excess]:
                del sc.rows[id_]


# ==================================================================================================================== #


from id_translation import Translator
from id_translation.fetching import MemoryFetcher


def create(ttl: float = 3600) -> Translator[str, str, int]:
    cache_access = InMemoryCacheAccess(ttl=ttl)
    fetcher = MemoryFetcher(
        data={"people": {1904: "Fred", 1999: "Sofia"}},
        cache_access=cache_access,
    )
    return Translator(fetcher)


# ==================================================================================================================== #
# By-ID translation populates the cache incrementally; repeating known IDs is served from memory.
translator = create()
print("first :", translator.translate([1904, 1999], "people"))  # cache miss -> fetch -> store
print("repeat:", translator.translate(1904, "people"))  # cache hit (1904 already cached)
