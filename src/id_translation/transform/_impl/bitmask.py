"""Transformations for translating bitmask fields."""

from collections.abc import Iterable, Mapping, MutableMapping
from itertools import filterfalse
from typing import TypedDict

from ..types import Transformer

IdType = int


class TomlOverrideRecord(TypedDict):
    id: IdType
    override: str


class BitmaskTransformer(Transformer[IdType]):
    """Transformations for translating bitmask fields.

    IDs must be integers.

    .. important::

       When using TOML config, dict keys must be strings. Use alternative format for `overrides`:

       .. code-block:: toml

          [transform.'<source>'.BitmaskTransformer]
          overrides = [
            { id = 0, override = "override-for-id=0" },
            { id = 1, override = "override-for-id=1" },
          ]

       Key names must match exactly, and IDs may not be repeated. For more information about TOML configuration, see
       :ref:`translator-config-transform`.

    Args:
        joiner: A string used to join bitmask flag labels.
        overrides: A dict ``{id: translation}``. Use to add or override the translation source.
        force_decomposition: If ``True``, ignore composite values in the translation source.

    Examples:
        Basic usage.

        >>> btr = BitmaskTransformer(overrides={0b000: "NOT_SET", 0b1000: "OVERFLOW!"})

        Create a :class:`.Translator` using bitmask transforms for the `'bitmasks'` source.

        >>> from id_translation import Translator
        >>> data = {"id": [1, 4, 8], "name": ["name-of-1", "name-of-4", "0b1000"]}
        >>> tra = Translator({"bitmasks": data}, transformers={"bitmasks": btr})

        Translate some bitmasks!

        >>> tra.translate((0b000, 0b101, 8), names="bitmasks")
        ('NOT_SET', '1:name-of-1 & 4:name-of-4', 'OVERFLOW!')

        Note that ``0='NOT_SET'`` was translated even though it's not in the ``data``, and that ``8='0b1000'`` was
        replaced by ``'OVERFLOW!'``, as per the overrides specified for the transformer.
    """

    def __init__(
        self,
        joiner: str = " & ",
        *,
        overrides: Mapping[IdType, str] | None = None,
        force_decomposition: bool = False,
    ) -> None:
        self._joiner = joiner
        self._force = force_decomposition
        if isinstance(overrides, list):
            # TOML keys must be strings, so we use a record format.
            overrides = self._from_toml_records(overrides)
        self._overrides = overrides or {}

    @classmethod
    def update_ids(cls, ids: set[IdType]) -> None:
        """Add decomposed bitmask values."""
        new_ids = set()
        for decomposed in map(cls.decompose_bitmask, ids):
            new_ids.update(decomposed)
        ids.update(new_ids)

    def update_translations(self, translations: dict[IdType, str]) -> None:
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

    def _create_composite_translation(self, bits: list[IdType], *, translations: Mapping[IdType, str]) -> str:
        return self._joiner.join(translations[idx] for idx in bits)

    def __repr__(self) -> str:
        overrides = self._overrides
        force_decomposition = self._force
        return f"{type(self).__name__}({self._joiner!r}, {overrides=}, {force_decomposition=})"

    @classmethod
    def decompose_bitmask(cls, i: int, /) -> list[int]:
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

        An integer `i` is decomposable if and only if `i > 2`, and `i` is not a power of two.

        Args:
            i: Any integer.

        Returns:
            ``True`` if `i` is decomposable into powers of two.
        """
        return i > 2 and ((i & (-i)) != i)  # noqa: PLR2004

    @staticmethod
    def _from_toml_records(records: list[TomlOverrideRecord]) -> dict[IdType, str]:
        permitted = {"id", "override"}

        overrides = {}
        for i, record in enumerate(records, start=1):
            if permitted != set(record):
                msg = f"Record {i}/{len(records)} is malformed: Expected keys {permitted} but got {record}"
                raise ValueError(msg)

            key = record["id"]
            if key in overrides:
                raise ValueError(f"Duplicate ID in record {i}/{len(records)}: {record=}")
            overrides[key] = record["override"]
        return overrides
