"""Classes used for ID and translation transformation."""

import typing as _t

from ..types import IdType as _IdType
from ..types import SourceType as _SourceType


@_t.runtime_checkable
class Transformer(_t.Protocol[_IdType]):
    """Transformation API type.

    Transformers are persistent entities owned by a single :class:`.Translator` instance. See the
    :class:`.BitmaskTransformer` for a concrete example.
    """

    def update_ids(self, ids: set[_IdType], /) -> None:
        """Transform a source-to-ids mapping dict.

        Called just before IDs are fetched from the source.

        .. note::

           Not called when the :class:`.Translator` is working offline.

        Args:
            ids: A collection of IDs from the `source`.
        """

    def update_translations(self, translations: dict[_IdType, str], /) -> None:
        """Update real translations.

        Called by the :class:`.MagicDict` during initialization.

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

        Callback function used by :class:`.MagicDict` whenever an unknown ID is requested.

        Args:
            key: An ID which is not present in the `translations`.
            translations: A mutable mapping of translations. Typically, the :class:`.MagicDict` caller itself.
        """


Transformers = dict[_SourceType, Transformer[_IdType]]
"""A dict ``{source: transformer}`` of initialized :class:`.Transformer` instances."""
