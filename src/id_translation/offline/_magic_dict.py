import logging
from typing import Any, Iterator, MutableMapping, Optional, Tuple

from rics.misc import tname

from .. import _uuid_utils
from ..transform.types import Transformer, TransformerStop
from ..types import IdType
from .types import TranslatedIds


class MagicDict(MutableMapping[IdType, str]):
    """Dictionary type for translated IDs.

    If `default_value` is given, it is used as the default answer for any calls to ``__getitem__`` where the key is
    not in `translated_ids`.

    Args:
        real_translations: A dict holding real translations.
        default_value: A string with exactly one or zero placeholders.
        enable_uuid_heuristics: Enabling may improve matching when :py:class:`~uuid.UUID`-like IDs are in use.
        transformer: Initialized :class:`.Transformer` instance.

    Examples:
        Behaviour with :attr:`default_value`.

        >>> magic = MagicDict(
        ...    {1999: "1999:Sofia", 1991: "1991:Richard"},
        ...    default_value="<Failed: id={!r}>",
        ... )
        >>> magic
        {1999: '1999:Sofia', 1991: '1991:Richard'}

        Calls to ``__getitem__`` and ``__contains__`` will never return ``False``.

        >>> magic[1999], 1999 in magic
        ('1999:Sofia', True)
        >>> magic["1999"], "1999" in magic
        ("<Failed: id='1999'>", True)

        Special handling for :py:class:`uuid.UUID` and ``UUID``-like strings improve matching.

        >>> from uuid import UUID
        >>> string_uuid = "550e8400-e29b-41d4-a716-446655440000"
        >>> magic = MagicDict(
        ...    {string_uuid: "Found!"},
        ...    enable_uuid_heuristics=True,
        ... )
        >>> magic
        {UUID('550e8400-e29b-41d4-a716-446655440000'): 'Found!'}

        >>> magic[string_uuid], magic[UUID(string_uuid)]
        ('Found!', 'Found!')

        Converting to a regular ``dict``.

        >>> dict(magic)
        {UUID('550e8400-e29b-41d4-a716-446655440000'): 'Found!'}

        Casting to ``dict`` removes all special handling.
    """

    LOGGER = logging.getLogger(__package__).getChild("MagicDict")

    def __init__(
        self,
        real_translations: TranslatedIds[IdType],
        default_value: str = None,
        enable_uuid_heuristics: bool = True,
        transformer: Transformer[IdType] = None,
    ) -> None:
        if enable_uuid_heuristics and real_translations:
            real_translations, enable_uuid_heuristics = _try_stringify_many(real_translations)

        self._real: TranslatedIds[IdType] = real_translations
        self._default = default_value
        self._cast_key = enable_uuid_heuristics

        self._try_add_missing_key = None
        if transformer is not None:
            transformer.update_translations(real_translations)
            self._try_add_missing_key = transformer.try_add_missing_key

    @property
    def default_value(self) -> Optional[str]:
        """Return the default string value to return for unknown keys, if any."""
        return self._default

    def _try_stringify(self, key: IdType) -> Any:
        return _uuid_utils.try_cast_one(key) if self._cast_key else key

    def __getitem__(self, key: IdType) -> str:
        key = self._on_read(key)
        if key in self._real or self.default_value is None:
            return self._real[key]

        return self.default_value.format(key)

    def __contains__(self, key: Any) -> bool:
        key = self._on_read(key)
        return self.default_value is not None or key in self._real

    def _on_read(self, key: IdType) -> IdType:
        key = self._try_stringify(key)
        if self._try_add_missing_key and key not in self._real:
            try:
                self._try_add_missing_key(key, translations=self)
            except TransformerStop as e:
                if self.LOGGER.isEnabledFor(logging.DEBUG):
                    call = f"{tname(self._try_add_missing_key, prefix_classname=True)}({key!r}, translations=self)"
                    self.LOGGER.debug(f"try_add_missing_key: {call} raised {e!r}. Dropping this callback function.")
                self._try_add_missing_key = None
        return key

    def __setitem__(self, key: IdType, value: str) -> None:
        key = self._on_write(key)
        self._real[key] = value

    def __delitem__(self, key: IdType) -> None:
        key = self._on_write(key)
        del self._real[key]

    def _on_write(self, key: IdType) -> IdType:
        key = self._try_stringify(key)
        return key

    def __len__(self) -> int:
        return len(self._real)

    def __iter__(self) -> Iterator[IdType]:
        return iter(self._real)

    def __repr__(self) -> str:
        return repr(self._real)


def _try_stringify_many(real_translations: TranslatedIds[IdType]) -> Tuple[TranslatedIds[IdType], bool]:
    original_ids = list(real_translations)
    try:
        new_keys = _uuid_utils.cast_many(original_ids)
    except (ValueError, AttributeError, TypeError):
        return real_translations, False  # Keys are not UUID-like.

    uuid_translations = {uuid: real_translations[idx] for uuid, idx in zip(new_keys, original_ids)}
    if len(real_translations) != len(uuid_translations):
        raise TypeError("Duplicate UUIDs found. Verify translation sources or set enable_uuid_heuristics=False.")

    return uuid_translations, True
