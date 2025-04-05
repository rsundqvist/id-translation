from abc import ABC, abstractmethod
from typing import Generic

from id_translation.fetching.types import FetchInstruction
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
    ) -> PlaceholderTranslations[SourceType] | None:
        """Load cached translations.

        If this method returns ``None``, the ``AbstractFetcher`` will use :meth:`~.AbstractFetcher.fetch_translations`
        instead. The fetcher will then call :meth:`store` using `instr` and the newly fetched translations.

        Args:
            instr: A :class:`.FetchInstruction`.

        Returns:
            Cached :class:`.PlaceholderTranslations` or ``None``.
        """

    @abstractmethod
    def store(
        self,
        instr: FetchInstruction[SourceType, IdType],
        translations: PlaceholderTranslations[SourceType],
    ) -> None:
        """Store fetched translations.

        .. note::

           This method will never be called with translations that were returned by :meth:`load`.

        In other words, this method will only be called if ``CacheAccess.load(instr)`` returns ``None``.

        .. hint::

           The ``CacheAccess`` is under no obligation to actually store `translations`.

        For example, implementations may choose only to cache data when the :attr:`.FetchInstruction.fetch_all`-property
        of the given `instr` is ``True``.

        Args:
            instr: The :class:`.FetchInstruction` which produced the `translations`.
            translations: A :class:`.PlaceholderTranslations` produced by :meth:`~.AbstractFetcher.fetch_translations`.
        """

    @property
    def parent(self) -> Fetcher[SourceType, IdType]:
        """Parent :class:`.Fetcher` instance.

        The owner, typically an :class:`.AbstractFetcher`, should call :meth:`.set_parent` during initialization.

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
            parent: A :class:`Fetcher`.

        Raises:
            RuntimeError: If a parent is already set.
        """
        if self._parent is not None:
            raise RuntimeError("parent already set")
        self._parent = parent
