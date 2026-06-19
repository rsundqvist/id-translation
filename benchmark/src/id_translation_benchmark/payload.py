"""Per-case payload construction: the translator + the containers it will translate.

We build an **offline** :class:`~id_translation.Translator` (the full universe of IDs is pre-fetched into an
in-memory map). This deliberately makes the fetch stage a cheap dict lookup so that the timed work is dominated by
the backend-specific *vectorized* stages -- extracting unique IDs from the container and broadcasting the
translated values back onto every row. That is the comparison we actually care about.
"""

from dataclasses import dataclass, field

from id_translation import Translator

from .backends import BACKENDS
from .capabilities import supports_enable_uuid_heuristics, supports_io_kwargs
from .data import SOURCE, IdType, make_ids, unique_ids

DEFAULT_FMT = "{id}:{name}"


@dataclass
class Payload:
    """Everything a candidate needs to translate one case, built outside the timed region."""

    translator: Translator
    containers: dict[str, object]
    n: int
    n_unique: int
    id_type: IdType
    expected_unique: dict = field(repr=False, default_factory=dict)

    def translate(self, backend: str, io_kwargs: dict | None = None) -> object:
        """Translate the container for ``backend`` (this is the timed call).

        ``io_kwargs`` is forwarded to the backend's :class:`~id_translation.dio.DataStructureIO`, e.g.
        ``{"fast": True}`` for polars or ``{"as_category": True}`` for pandas. It is only passed when the
        installed version supports it (so the suite runs against pre-1.1.0 releases during backfill).
        """
        container = self.containers[backend]
        if io_kwargs is None or not supports_io_kwargs():
            return self.translator.translate(container, names=SOURCE)
        return self.translator.translate(container, names=SOURCE, io_kwargs=io_kwargs)


def make_translator(unique: list, *, fmt: str = DEFAULT_FMT, enable_uuid_heuristics: bool = False) -> Translator:
    """Build an offline translator covering exactly ``unique`` IDs.

    ``enable_uuid_heuristics`` is required for the ``uuid`` ID type: polars stringifies ``UUID`` objects when
    extracting from an ``Object`` column, so the heuristics are what let those strings match the ``UUID`` keys.
    """
    names = [f"name-of-{i}" for i in unique]
    fetcher_data = {SOURCE: {"id": unique, "name": names}}
    if enable_uuid_heuristics and supports_enable_uuid_heuristics():
        return Translator(fetcher_data, fmt=fmt, enable_uuid_heuristics=True)
    return Translator(fetcher_data, fmt=fmt)


def build_payload(
    *,
    n: int,
    n_unique: int | None,
    id_type: IdType,
    backends: list[str],
    fmt: str = DEFAULT_FMT,
) -> Payload:
    """Construct a :class:`Payload` for one ``(n, n_unique, id_type)`` case.

    Only the containers for the requested ``backends`` are materialized.
    """
    ids = make_ids(n, n_unique=n_unique, id_type=id_type)
    unique = unique_ids(ids)
    translator = make_translator(unique, fmt=fmt, enable_uuid_heuristics=id_type == "uuid")

    containers = {name: BACKENDS[name].build(ids) for name in backends}
    return Payload(
        translator=translator,
        containers=containers,
        n=n,
        n_unique=len(unique),
        id_type=id_type,
    )
