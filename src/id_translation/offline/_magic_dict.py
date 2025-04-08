import logging
from collections.abc import Iterator, MutableMapping
from typing import Any
from uuid import UUID

from .. import _uuid_utils
from ..transform.types import Transformer
from ..types import IdType
from ._format import Format
from .types import TranslatedIds


class MagicDict(MutableMapping[IdType, str]):
    """Dictionary type for translated IDs.

    A ``dict``-like mapping which returns "real" values if present in a backing dict. Values for unknown keys are
    generated using the :attr:`default_value`.

    Args:
        real_translations: A dict holding :attr:`real` translations.
        default_value: A string with exactly one or zero positional placeholders.
        enable_uuid_heuristics: Improves matching when :py:class:`~uuid.UUID`-like IDs are in use. Forcibly set to
            ``False`` if any of the `real_translations` are not ``UUID``-like.
        transformer: Initialized :class:`.Transformer` instance. The :meth:`.Transformer.update_translations`-method is
            called after UUID heuristics are applied.

    Examples:
        **Similarities with the built-in dict**

        >>> magic = MagicDict({1999: "Sofia", 1991: "Richard"})

        Iteration, equality, and length are based on the :attr:`real`  values.

        >>> magic
        {1999: 'Sofia', 1991: 'Richard'}
        >>> len(magic)
        2
        >>> list(magic)
        [1999, 1991]
        >>> magic.real == magic
        True
        >>> magic == {1999: "Sofia"}  # Element missing
        False

        As you'd expect, casting to a regular ``dict`` removes all special handling.

        **Differences from the built-in dict**

        Methods ``__getitem__`` and ``__contains__`` never fail or return False. Using a default with ``get`` will
        generate a value rather than using the provided default.

        >>> magic[1999]
        'Sofia'
        >>> magic[2019]
        '<Failed: id=2019>'
        >>> magic.get(2019, "foo")  # doctest: +SKIP
        '<Failed: id=2019>'

        **ID translation heuristics**

        Special handling for :py:class:`uuid.UUID` and ``UUID``-like strings improve matching.

        >>> string_uuid = "550e8400-e29b-41d4-a716-446655440000"
        >>> magic = MagicDict(
        ...     {string_uuid: "Found!"},
        ...     enable_uuid_heuristics=True,
        ... )
        >>> magic
        {UUID('550e8400-e29b-41d4-a716-446655440000'): 'Found!'}

        When ``enable_uuid_heuristics=True``, the ``MagicDict`` will attempt to cast keys to :class:`uuid.UUID`.

        >>> from uuid import UUID
        >>> magic[string_uuid], magic[UUID(string_uuid)]
        ('Found!', 'Found!')

        Keys that cannot be converted are left as-is.

        >>> magic["Hello"] = "World!"
        >>> magic["unknown"], magic["Hello"]
        ("<Failed: id='unknown'>", 'World!')

        To further customize ID matching behaviour, refer to the :class:`.Transformer` interface.
    """

    LOGGER = logging.getLogger(__package__).getChild("MagicDict")

    def __init__(
        self,
        real_translations: TranslatedIds[IdType],
        default_value: str = Format(Format.DEFAULT_FAILED).fstring(positional=True),
        enable_uuid_heuristics: bool = True,
        transformer: Transformer[IdType] | None = None,
    ) -> None:
        if enable_uuid_heuristics and real_translations:
            real_translations, enable_uuid_heuristics = _try_stringify_many(real_translations)
        if transformer:
            transformer.update_translations(real_translations)

        self._real: TranslatedIds[IdType] = real_translations
        self._default = self._verify_default_value(default_value)
        self._cast_key = enable_uuid_heuristics
        self._transformer = transformer

    def get(self, key: IdType, /, _: Any = None) -> str:
        """Same as ``__getitem__``.

        Values for missing keys are generated from :attr:`default_value`.
        """
        return self[key]

    def real_get(self, key: IdType) -> str | None:
        """Attempt to get an actual translation.

        This method behaves like ``MagicDict.__getitem__``, applying all appropriate heuristics **except** for falling
        back to the :attr:`default_value`. Returns ``None`` if the `key` cannot be mapped to a real values, like the
        regular ``dict.get`` method would.

        To bypass the heuristics, use :attr:`real` and :meth:`dict.get` instead. Note that the backing dict may still
        contain mappings added transformers, since the :meth:`.Transformer.update_translations` interface is called
        during initialization.
        """
        if key in self._real:
            return self._real[key]

        key = self._on_read(key)
        return self._real.get(key)

    def real_contains(self, key: IdType, /) -> bool:
        """Check if an actual translation exists using :meth:`real_get`."""
        return self.real_get(key) is not None

    @property
    def real(self) -> dict[IdType, str]:
        """Returns the backing dict."""
        return self._real

    @property
    def default_value(self) -> str:
        """Return the default string value to return for unknown keys, if any."""
        return self._default

    def _try_stringify(self, key: IdType) -> Any:
        return _uuid_utils.try_cast_one(key) if self._cast_key else key

    def __getitem__(self, key: IdType) -> str:
        value = self.real_get(key)
        return self.default_value.format(key) if value is None else value

    def __contains__(self, key: Any) -> bool:
        """Always returns ``True``."""
        return True  # We can always render something with default_value.

    def _on_read(self, key: IdType) -> IdType:
        key = self._try_stringify(key)
        if self._transformer and key not in self._real:
            self._transformer.try_add_missing_key(key, translations=self)
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

    @classmethod
    def _verify_default_value(cls, default_value: str) -> str:
        for sample in "id", 0, UUID(int=0):
            try:
                default_value.format(sample)
                return default_value  # Formatting OK
            except KeyError as e:
                raise ValueError(f"Bad {default_value=}") from e
            except Exception:  # noqa: S110
                pass  # Attribute error, value error, etc. Happens naturally when the sample type is wrong.

        return default_value


def _try_stringify_many(real_translations: TranslatedIds[IdType]) -> tuple[TranslatedIds[IdType], bool]:
    original_ids = list(real_translations)
    if len(original_ids) == 0:
        return real_translations, True

    new_keys = _uuid_utils.try_cast_many(original_ids)
    if not isinstance(new_keys[0], UUID):
        return real_translations, False  # Keys are not UUID-like.

    uuid_translations = {uuid: real_translations[idx] for uuid, idx in zip(new_keys, original_ids, strict=True)}
    if len(real_translations) != len(uuid_translations):
        raise TypeError("Duplicate UUIDs found. Verify translation sources or set enable_uuid_heuristics=False.")

    return uuid_translations, True
