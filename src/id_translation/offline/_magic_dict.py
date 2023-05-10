from typing import Any, Iterator, Mapping, Optional, Tuple

from .. import _uuid_utils
from ..types import IdType
from .types import TranslatedIds


class MagicDict(Mapping[IdType, str]):
    """Immutable mapping for translated IDs.

    If `default_value` is given, it is used as the default answer for any calls to `__getitem__` where the key is
    not in `translated_ids`.

    Args:
        real_translations: A dict holding real translations.
        default_value: A string with exactly one or zero placeholders.
        enable_uuid_heuristics: Enabling may improve matching when :py:class:`~uuid.UUID`-like IDs are in use.
    """

    def __init__(
        self,
        real_translations: TranslatedIds[IdType],
        default_value: str = None,
        enable_uuid_heuristics: bool = True,
    ) -> None:
        if enable_uuid_heuristics and real_translations:
            real_translations, enable_uuid_heuristics = _try_stringify(real_translations)

        self._real: TranslatedIds[IdType] = real_translations
        self._default = default_value
        self._cast_key = enable_uuid_heuristics

    @property
    def default_value(self) -> Optional[str]:
        """Return the default string value to return for unknown keys, if any."""
        return self._default

    def _try_stringify(self, key: IdType) -> Any:
        return _uuid_utils.try_cast_one(key) if self._cast_key else key

    def __getitem__(self, key: IdType) -> str:
        key = self._try_stringify(key)
        if key in self._real or self.default_value is None:
            return self._real[key]

        return self.default_value.format(key)

    def __contains__(self, key: Any) -> bool:
        key = self._try_stringify(key)
        return self.default_value is not None or key in self._real

    def __len__(self) -> int:
        return len(self._real)

    def __iter__(self) -> Iterator[IdType]:
        return iter(self._real)

    def __repr__(self) -> str:
        return repr(self._real)


def _try_stringify(real_translations: TranslatedIds[IdType]) -> Tuple[TranslatedIds[IdType], bool]:
    original_keys = list(real_translations)
    try:
        new_keys = _uuid_utils.cast_many(original_keys)
    except (ValueError, AttributeError, TypeError):
        return real_translations, False  # Keys are not UUID-like.

    uuid_translations = {uuid: real_translations[k] for uuid, k in zip(new_keys, original_keys)}
    if len(real_translations) != len(uuid_translations):
        raise TypeError("Duplicate UUIDs found. Verify translation sources or set enable_uuid_heuristics=False.")

    return uuid_translations, True
