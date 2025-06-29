"""A naive caching solution.

Downloaded from:
    https://id-translation.readthedocs.io/en/stable/documentation/examples/caching/caching.html

This implementation provides:
    * Per-source cache timeout.
    * Cache write on FetchInstruction.fetch_all=True.
    * Local cache storage using feather.

This is a naive implementation whose primary purpose is to provide a concrete
example of the CacheAccess pattern. Keep in mind that load() method will be
called every single time that data is requested, so slow operations such as
disk reads should be used with care.
"""

from datetime import datetime
from pathlib import Path

import pandas as pd

from id_translation.fetching import CacheAccess
from id_translation.fetching.types import FetchInstruction
from id_translation.offline.types import PlaceholderTranslations
from id_translation.types import IdType, SourceType


class MyCacheAccess(CacheAccess[SourceType, IdType]):
    """Example caching implementation."""

    def __init__(self, root: str, ttl: int) -> None:
        super().__init__()
        self._root = Path(root)
        self._ttl = ttl  # In seconds

        self._root.mkdir(parents=True, exist_ok=True)

    def store(
        self,
        instr: FetchInstruction[SourceType, IdType],
        translations: PlaceholderTranslations[SourceType],
    ) -> None:
        if not instr.fetch_all:
            print(
                f"Refuse caching of source={instr.source!r}"
                " since FetchInstruction.fetch_all=False."
            )
            return

        df = translations.to_pandas()
        path = self._root / f"{translations.source}.ftr"
        print(f"Store cache at path='{path}'.")
        df.to_feather(path)

    def load(
        self,
        instr: FetchInstruction[SourceType, IdType],
    ) -> PlaceholderTranslations[SourceType] | None:
        path = self._root / f"{instr.source}.ftr"

        if not path.exists():
            print(f"Cache at path='{path}' does not exist.")
            return None

        age = self.age_in_seconds(path)

        if age > self._ttl:
            print(f"Reject cache ({age=} > ttl={self._ttl}) at path='{path}'.")
            return None

        print(f"Load cache (age={age} <= {self._ttl}=ttl) at path='{path}'.")
        df = pd.read_feather(path)
        return PlaceholderTranslations.from_dataframe(instr.source, df)

    @staticmethod
    def age_in_seconds(path: Path) -> int:
        timestamp = path.stat().st_mtime
        modified = datetime.fromtimestamp(timestamp)
        seconds = (datetime.now() - modified).total_seconds()
        return round(seconds)


# ==================================================================================================================== #


from id_translation.fetching import MemoryFetcher
from id_translation import Translator


def create() -> Translator[str, str, int]:
    cache_access = MyCacheAccess(root="./cache/", ttl=3600)
    fetcher = MemoryFetcher(
        data={"people": {1904: "Fred"}},
        cache_access=cache_access,
    )
    return Translator(fetcher)


# ==================================================================================================================== #
# ======== Stage 1 ====================================================
translator = create()
print("person=", translator.translate(1904, "people"))

# ======== Stage 2 ====================================================
translator.go_offline()
print("person=", translator.translate(1904, "people"))

# ======== Stage 3 ====================================================
print("person=", create().translate(1904, "people"))

# ==================================================================================================================== #
import os

os.remove("cache/people.ftr")
