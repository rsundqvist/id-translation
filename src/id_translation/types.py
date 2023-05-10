"""Types used for translation.

This module cannot be called just `types` as that will make MyPY complain.
"""
import abc as _abc
import typing as _type
from typing import TYPE_CHECKING
from uuid import UUID as _UUID

if TYPE_CHECKING:
    import pandas  # noqa: F401
    from numpy.typing import NDArray

Translatable = _type.TypeVar(
    "Translatable",
    # Primitive types
    str,
    int,
    _type.Dict,  # type: ignore[type-arg]  # TODO: Need Higher-Kinded TypeVars
    _type.Sequence,  # type: ignore[type-arg]  # TODO: Need Higher-Kinded TypeVars
    "NDArray",  # type: ignore[type-arg]  # TODO: Need Higher-Kinded TypeVars
    "pandas.DataFrame",
    "pandas.Index",
    "pandas.Series",
)
"""Enumeration of translatable types.

The only truly :attr:`Translatable` types are ``int`` and ``str``. Working with single IDs is rarely desirable in
practice, so collections such as sequences (lists, tuples, :mod:`numpy` arrays) and dict values of sequences of
primitives (or plain primitives) may be translated as well. Special handling is also implemented for :mod:`pandas`
types.
"""

ID: str = "id"
"""Name of the ID placeholder."""

NameType = _type.TypeVar("NameType", bound=_type.Hashable)
"""Type used to label collections of IDs, such as the column names in a DataFrame or the keys of a dict."""

IdType = _type.TypeVar("IdType", int, str, _UUID)
"""Type of the value being translated into human-readable labels."""

SourceType = _type.TypeVar("SourceType", bound=_type.Hashable)
"""Type used to describe sources. Typically a string for things like files and database tables."""

NamesPredicate = _type.Callable[[NameType], bool]
"""A predicate type on names."""
NameTypes = _type.Union[NameType, _type.Iterable[NameType]]
"""A union of a name type, or an iterable thereof."""
Names = _type.Union[NameTypes[NameType], NamesPredicate[NameType]]
"""Acceptable name types."""


class HasSources(_abc.ABC, _type.Generic[SourceType]):
    """Indicates that `sources` and `placeholders` are available."""

    @property
    def sources(self) -> _type.List[SourceType]:
        """A list of known Source names, such as ``cities`` or ``languages``."""
        return list(self.placeholders)

    @property
    @_abc.abstractmethod
    def placeholders(self) -> _type.Dict[SourceType, _type.List[str]]:
        """Placeholders for all known Source names, such as ``id`` or ``name``.

        These are the (possibly unmapped) placeholders that may be used for translation.

        Returns:
            A dict ``{source: [placeholders..]}``.
        """  # noqa: DAR202
