from abc import abstractmethod
from collections.abc import Iterable
from typing import Generic

from ..offline.types import SourcePlaceholderTranslations
from ..types import HasSources, IdType, SourceType
from .types import IdsToFetch


class Fetcher(Generic[SourceType, IdType], HasSources[SourceType]):
    """Interface for fetching translations from an external source."""

    @abstractmethod
    def initialize_sources(self, task_id: int = -1, *, force: bool = False) -> None:
        """Perform source discovery.

        Args:
            task_id: Used for logging.
            force: If ``True``, perform full discovery even if sources are already known.
        """

    @property
    @abstractmethod
    def allow_fetch_all(self) -> bool:
        """Flag indicating whether the :meth:`~.fetching.Fetcher.fetch_all` operation is permitted."""

    def close(self) -> None:
        """Close the ``Fetcher``. Does nothing by default."""

    @property
    @abstractmethod
    def online(self) -> bool:
        """Return connectivity status. If ``False``, no new translations may be fetched."""

    @property
    def optional(self) -> bool:
        """Return ``True`` if this fetcher has been marked as `optional`.

        In multi-fetcher mode, optional fetchers may be discarded if :attr:`~.HasSources.sources` cannot be resolved
        (raises an exception). Default value is ``False``.

        Returns:
            Optionality status.
        """
        return False

    @abstractmethod
    def fetch(
        self,
        ids_to_fetch: Iterable[IdsToFetch[SourceType, IdType]],
        placeholders: Iterable[str] = (),
        *,
        required: Iterable[str] = (),
        task_id: int | None = None,
        enable_uuid_heuristics: bool = False,
    ) -> SourcePlaceholderTranslations[SourceType]:
        """Retrieve placeholder translations from the source.

        Args:
            ids_to_fetch: An iterable of :class:`.IdsToFetch`.
            placeholders: All desired placeholders in preferred order.
            required: Placeholders that must be included in the response.
            task_id: Used for logging.
            enable_uuid_heuristics: If set, apply heuristics to improve matching with :py:class:`~uuid.UUID`-like IDs.

        Returns:
            A mapping ``{source: PlaceholderTranslations}`` of translation elements.

        Raises:
            UnknownPlaceholderError: For placeholder(s) that are unknown to the ``Fetcher``.
            UnknownSourceError: For sources(s) that are unknown to the ``Fetcher``.
            ForbiddenOperationError: If trying to fetch all IDs when not possible or permitted.
            ImplementationError: For errors made by the inheriting implementation.

        Notes:
            Placeholders are usually columns in relational database applications. These are the components which are
            combined to create ID translations. See :class:`~id_translation.offline.Format` documentation for details.
        """

    @abstractmethod
    def fetch_all(
        self,
        placeholders: Iterable[str] = (),
        *,
        required: Iterable[str] = (),
        task_id: int | None = None,
        enable_uuid_heuristics: bool = False,
    ) -> SourcePlaceholderTranslations[SourceType]:
        """Fetch as much data as possible.

        Args:
            placeholders: All desired placeholders in preferred order.
            required: Placeholders that must be included in the response.
            task_id: Used for logging.
            enable_uuid_heuristics: If set, apply heuristics to improve matching with :py:class:`~uuid.UUID`-like IDs.

        Returns:
            A mapping ``{source: PlaceholderTranslations}`` of translation elements.

        Raises:
            ForbiddenOperationError: If fetching all IDs is not possible or permitted.
            UnknownPlaceholderError: For placeholder(s) that are unknown to the ``Fetcher``.
            ImplementationError: For errors made by the inheriting implementation.
        """
