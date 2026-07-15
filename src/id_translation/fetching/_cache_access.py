from abc import ABC, abstractmethod
from typing import Generic

from id_translation.fetching.types import FetchInstruction, PartialCacheHit
from id_translation.offline.types import PlaceholderTranslations
from id_translation.types import IdType, SourceType

from ._fetcher import Fetcher


class CacheAccess(ABC, Generic[SourceType, IdType]):
    """Interface for user-managed caching.

    To enable caching, implement the abstract methods of the ``CacheAccess`` interface and pass it to the fetcher. See
    the :ref:`🚀 examples page <caching_example>` to get started.
    """

    def __init__(self) -> None:
        self._parent: Fetcher[SourceType, IdType] | None = None

    @property
    def enabled(self) -> bool:
        """Return the enabled status for this ``CacheAccess``.

        Returns ``True`` by default. If this property is ``False``, no other methods will be called.
        """
        return True

    @abstractmethod
    def load(
        self,
        instr: FetchInstruction[SourceType, IdType],
    ) -> PlaceholderTranslations[SourceType] | PartialCacheHit[SourceType, IdType] | None:
        """Load cached translations.

        Return one of:

        * A :class:`~id_translation.offline.types.PlaceholderTranslations` covering every requested ID (a complete hit). It is used as-is;
          :meth:`~id_translation.fetching.CacheAccess.store` is not called.
        * ``None`` (a miss). The ``AbstractFetcher`` calls :meth:`~id_translation.fetching.AbstractFetcher.fetch_translations` for all IDs and
          then :meth:`~id_translation.fetching.CacheAccess.store`.
        * A :class:`~id_translation.fetching.types.PartialCacheHit`. The fetcher fetches only the *missing* IDs, merges them with the cached rows,
          and calls :meth:`~id_translation.fetching.CacheAccess.store` with the freshly fetched complement. Not supported for
          :attr:`~id_translation.fetching.types.FetchInstruction.fetch_all` instructions (return ``None`` or a complete hit instead).

        Args:
            instr: A :class:`~id_translation.fetching.types.FetchInstruction`.

        Returns:
            Cached :class:`~id_translation.offline.types.PlaceholderTranslations`, a :class:`~id_translation.fetching.types.PartialCacheHit`, or
            ``None``.
        """

    @abstractmethod
    def store(
        self,
        instr: FetchInstruction[SourceType, IdType],
        translations: PlaceholderTranslations[SourceType],
    ) -> None:
        """Store fetched translations.

        .. note::

           This method will never be called with translations that were returned by :meth:`~id_translation.fetching.CacheAccess.load`.

        In other words, this method will only be called if ``CacheAccess.load(instr)`` returns ``None``.

        .. hint::

           The ``CacheAccess`` is under no obligation to actually store `translations`.

        For example, implementations may choose only to cache data when the
        :attr:`FetchInstruction.fetch_all <id_translation.fetching.types.FetchInstruction.fetch_all>`-property
        of the given `instr` is ``True``.

        Args:
            instr: The :class:`~id_translation.fetching.types.FetchInstruction` which produced the `translations`.
            translations: A :class:`~id_translation.offline.types.PlaceholderTranslations` produced by
                :meth:`~id_translation.fetching.AbstractFetcher.fetch_translations`.
        """

    @property
    def parent(self) -> Fetcher[SourceType, IdType]:
        """Parent :class:`~id_translation.fetching.Fetcher` instance.

        The owner, typically an :class:`~id_translation.fetching.AbstractFetcher`, should call :meth:`~id_translation.fetching.CacheAccess.set_parent`
        during initialization.

        Returns:
            The fetcher that owns this ``CacheAccess``.

        Raises:
            RuntimeError: If called before the parent is set.
        """
        if self._parent is None:
            raise RuntimeError("parent not set")
        return self._parent

    def set_parent(self, parent: Fetcher[SourceType, IdType]) -> None:
        """Set parent instance.

        Args:
            parent: A :class:`~id_translation.fetching.Fetcher`.

        Raises:
            RuntimeError: If a parent is already set.
        """
        if self._parent is not None:
            raise RuntimeError("parent already set")
        self._parent = parent
