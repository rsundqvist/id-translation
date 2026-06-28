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

* Partial hits: load() returns a PartialCacheHit holding whatever hot rows we
  have; the fetcher fetches only the uncovered IDs and merges them (calling
  store() with just the complement). We return None only when nothing is cached
  for the source, or we lack a requested placeholder.
* Simplification -- a source is assumed to always be fetched with the same
  placeholders. We store one row per ID for the most recent placeholder layout
  and reset a source's cache if its placeholders change. A production cache that
  mixes placeholder sets per source would instead key rows by placeholder layout.
"""

import time
from dataclasses import dataclass

from id_translation.fetching import CacheAccess
from id_translation.fetching.types import FetchInstruction, PartialCacheHit
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
    ) -> PartialCacheHit[SourceType, IdType] | None:
        if instr.ids is None:
            return None  # An accumulated cache cannot prove it holds *all* IDs (fetch_all).

        sc = self._cache.get(instr.source)
        if sc is None or not set(instr.placeholders).issubset(sc.placeholders):
            # Nothing cached for this source, or we lack a requested placeholder. Let the fetcher fetch everything;
            # store() will (re)set the layout.
            return None

        deadline = time.monotonic() - self._ttl
        records = [sc.rows[id_][1] for id_ in instr.ids if id_ in sc.rows and sc.rows[id_][0] >= deadline]

        # Return whatever subset is hot; the fetcher fetches the rest at our layout and merges. `covered` is left to
        # default to the IDs in these rows, so any missing/expired IDs are re-fetched (and re-cached via store()).
        return PartialCacheHit(
            PlaceholderTranslations(
                source=instr.source,
                placeholders=sc.placeholders,
                records=records,
                id_pos=sc.id_pos,
                placeholder_aliases=dict(sc.aliases),
            )
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
# By-ID translation populates the cache incrementally; subsequent calls fetch only the uncovered IDs.
translator = create()
print("first  :", translator.translate(1904, "people"))  # miss -> fetch {1904} -> store
print("partial:", translator.translate([1904, 1999], "people"))  # 1904 served from memory, only 1999 fetched
