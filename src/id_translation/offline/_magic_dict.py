from typing import Any, Iterator, Mapping, Optional

from ..types import IdType
from .types import TranslatedIds


class MagicDict(Mapping[IdType, str]):
    """Immutable mapping for translated IDs.

    If `default_value` is given, it is used as the default answer for any calls to `__getitem__` where the key is
    not in `translated_ids`.

    Args:
        real_translations: A dict holding real translations.
        default_value: A string with exactly one or zero placeholders.
    """

    def __init__(
        self,
        real_translations: TranslatedIds[IdType],
        default_value: str = None,
    ) -> None:
        self._real: TranslatedIds[IdType] = real_translations
        self._default = default_value

    @property
    def default_value(self) -> Optional[str]:
        """Return the default string value to return for unknown keys, if any."""
        return self._default  # pragma: no cover

    def __getitem__(self, key: IdType) -> str:
        if key in self._real or self._default is None:
            return self._real[key]

        return self._default.format(key)

    def __contains__(self, idx: Any) -> bool:
        return self._default is not None or idx in self._real  # pragma: no cover

    def __len__(self) -> int:
        return len(self._real)  # pragma: no cover

    def __iter__(self) -> Iterator[IdType]:
        return iter(self._real)  # pragma: no cover

    def __repr__(self) -> str:
        return repr(self._real)  # pragma: no cover
