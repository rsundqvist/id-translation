"""Transformations for translating bitmask fields."""

from itertools import filterfalse
from typing import Dict, Iterable, List, Literal, Mapping, MutableMapping, Set, Union

from ..types import Transformer

IdType = int
TomlOverrideRecord = Dict[Literal["id", "override"], Union[IdType, str]]  # TODO(3.11, -3.8, -3.9, -3.10) use TypedDict


class BitmaskTransformer(Transformer[IdType]):
    """Transformations for translating bitmask fields.

    Args:
        joiner: A string used to join bitmask flag labels.
        overrides: A dict ``{id: translation}``. Use to add or override the translation source.
        force_decomposition: If ``True``, ignore composite values in the translation source and in the `overrides`. This
            will force use of the `joiner`-based format.
    """

    def __init__(
        self,
        joiner: str = " & ",
        *,
        overrides: Mapping[IdType, str] = None,
        force_decomposition: bool = False,
    ) -> None:
        self._joiner = joiner
        self._force = force_decomposition
        if isinstance(overrides, list):
            # TOML keys must be strings, so we use a record format.
            overrides = self._from_toml_records(overrides)
        self._overrides = overrides or {}

    @classmethod
    def update_ids(cls, ids: Set[IdType]) -> None:
        """Add decomposed bitmask values."""
        new_ids = set()
        for decomposed in map(cls.decompose_bitmask, ids):
            new_ids.update(decomposed)
        ids.update(new_ids)

    def update_translations(self, translations: Dict[IdType, str]) -> None:
        """Join decomposed bitmask values using the `joiner` string."""
        ids_to_update: Iterable[IdType] = filter(self.is_decomposable, translations)
        if not self._force:
            ids_to_update = filterfalse(translations.__contains__, ids_to_update)
        ids_to_update = list(ids_to_update)

        translations.update(self._overrides)
        new_translations = {
            bitmask: self._create_composite_translation(self.decompose_bitmask(bitmask), translations=translations)
            for bitmask in ids_to_update
        }

        translations.update(new_translations)
        translations.update(self._overrides)

    def try_add_missing_key(self, key: IdType, /, *, translations: MutableMapping[IdType, str]) -> None:
        """Join decomposed bitmask values using the `joiner` string."""
        bits = self.decompose_bitmask(key)
        if not bits:
            return
        try:
            translations[key] = self._create_composite_translation(bits, translations=translations)
        except KeyError:
            return

    def _create_composite_translation(self, bits: List[IdType], *, translations: Mapping[IdType, str]) -> str:
        return self._joiner.join(translations[idx] for idx in bits)

    def __repr__(self) -> str:
        overrides = self._overrides
        force_decomposition = self._force
        return f"{type(self).__name__}({self._joiner!r}, {overrides=}, {force_decomposition=})"

    @classmethod
    def decompose_bitmask(cls, i: int, /) -> List[int]:
        """Decompose a bitmask into powers of two.

        If `i` is not :attr:`decomposable <is_decomposable>`, an empty list is returned.

        Args:
            i: Any integer.

        Returns:
            A decomposition of `i` into powers of two.
        """
        if not cls.is_decomposable(i):
            return []

        powers = []
        x = 1
        while x <= i:
            if x & i:
                powers.append(x)
            x <<= 1
        return powers

    @classmethod
    def is_decomposable(cls, i: int, /) -> bool:
        """Check if `i` is decomposable into bitmask values.

        An integer ``i`` is decomposable if it is:
            1. positive, and
            2. not a power of two

        Args:
            i: Any integer.

        Returns:
            ``True`` if `i` is decomposable into powers of two.
        """
        return i > 2 and ((i & (-i)) != i)

    @staticmethod
    def _from_toml_records(records: List[TomlOverrideRecord]) -> Dict[IdType, str]:
        keys = ("id", "override")

        overrides = {}
        for i, record in enumerate(records, start=1):
            if set(record) != set(keys):
                raise ValueError(f"Record {i}/{len(records)} is malformed: Expected keys {keys} but got: {record}")

            key = record["id"]
            if key in overrides:
                raise ValueError(f"Duplicate ID in record {i}/{len(records)}: {record=}")
            overrides[key] = record["override"]
        return overrides  # type: ignore[return-value]
