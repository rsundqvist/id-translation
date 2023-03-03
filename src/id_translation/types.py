"""Types used for translation.

This module cannot be called just `types` as that will make MyPY complain.
"""
from typing import TYPE_CHECKING, Callable, Dict, Hashable, Iterable, Sequence, TypeVar as _TypeVar, Union

if TYPE_CHECKING:
    import pandas  # noqa: F401
    from numpy.typing import NDArray

Translatable = _TypeVar(
    "Translatable",
    # Primitive types
    str,
    int,
    Dict,  # type: ignore[type-arg]  # TODO: Need Higher-Kinded TypeVars
    Sequence,  # type: ignore[type-arg]  # TODO: Need Higher-Kinded TypeVars
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

NameType = _TypeVar("NameType", bound=Hashable)
"""Type used to label collections of IDs, such as the column names in a DataFrame or the keys of a dict."""

IdType = _TypeVar("IdType", int, str)
"""Type of the value being translated into human-readable labels."""

SourceType = _TypeVar("SourceType", bound=Hashable)
"""Type used to describe sources. Typically a string for things like files and database tables."""

NamesPredicate = Callable[[NameType], bool]
"""A predicate type on names."""
NameTypes = Union[NameType, Iterable[NameType]]
"""A union of a name type, or an iterable thereof."""
Names = Union[NameTypes[NameType], NamesPredicate[NameType]]
"""Acceptable name types."""
