"""Classes used for ID and translation transformation."""

import typing as _t

from ..types import IdType as _IdType
from ..types import SourceType as _SourceType


@_t.runtime_checkable
class Transformer(_t.Protocol[_IdType]):
    """Transformation API type.

    .. warning::

       The :meth:`~id_translation.transform.types.Transformer.update_ids`-method is **not** called when the :class:`~id_translation.Translator` is
       working offline.

    Transformers are persistent entities owned by a single :class:`~id_translation.Translator` instance. See the
    :class:`~id_translation.transform.BitmaskTransformer` for a concrete example.
    """

    def update_ids(self, ids: set[_IdType], /) -> None:
        """Transform a source-to-ids mapping dict.

        Called just before IDs are fetched from the source.

        Args:
            ids: A collection of IDs from the `source`.
        """

    def update_translations(self, translations: dict[_IdType, str], /) -> None:
        """Update real translations.

        Called by the :class:`~id_translation.offline.MagicDict` during initialization.

        Args:
            translations: A dict of real translations ``{id: translation_string}``.
        """

    def try_add_missing_key(
        self,
        key: _IdType,
        /,
        *,
        translations: _t.MutableMapping[_IdType, str],
    ) -> None:
        """Attempt to create and add a translation for an unknown ID.

        Callback function used by :class:`~id_translation.offline.MagicDict` whenever an unknown ID is requested.

        Args:
            key: An ID which is not present in the `translations`.
            translations: A mutable mapping of translations. Typically, the :class:`~id_translation.offline.MagicDict` caller itself.
        """


Transformers = dict[_SourceType, Transformer[_IdType]]
"""A dict ``{source: transformer}`` of initialized :class:`~id_translation.transform.types.Transformer` instances."""
