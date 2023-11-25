"""Classes used for ID and translation transformation."""
import typing as _t

from ..types import IdType as _IdType


@_t.runtime_checkable
class Transformer(_t.Protocol[_IdType]):
    """Transformation API type.

    Transformers are persistent entities owned by a single :class:`.Translator` instance.

    Implementing :attr:`try_add_missing_key` is optional. Raise :class:`TransformerStop` to prevent calling the
    method multiple times.
    """

    def update_ids(self, ids: _t.Set[_IdType]) -> None:
        """Transform a source-to-ids mapping dict.

        Called just before IDs are fetched from the source.

        Args:
            ids: A collection of IDs from the `source`.
        """

    def update_translations(self, translations: _t.Dict[_IdType, str]) -> None:
        """Transform a translations.

        Called by the :class:`.MagicDict` during initialization.

        Args:
            translations: A dict of real translations ``{id: translation_string}``.
        """

    def try_add_missing_key(self, key: _IdType, /, *, translations: _t.MutableMapping[_IdType, str]) -> None:
        """Attempt to create and add a translation for an unknown ID.

        Callback function used by :class:`.MagicDict` when unknown IDs are requested. Raise :class:`.TransformerStop` to
        prevent calling this method.

        Args:
            key: An ID which is not present in the `translations`.
            translations: A mutable mapping of translations. Typically, the :class:`.MagicDict` caller itself.

        Raises:
            TransformerStop: If this method should not be called (again).
        """
        raise TransformerStop("not implemented")


class TransformerStop(ValueError):
    """Error indicating that this transformer method should not be called again.

    Transformers may raise this exception at any point, after which the method of that instance will not be called again
    by the caller which caught the exception.
    """
