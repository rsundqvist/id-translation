"""Types used for translation.

.. hint::

   Use :func:`.register_io` to register custom :class:`.DataStructureIO` implementations.

Rules of thumb
--------------
* The :attr:`IdTypes` are the only `"truly"` translatable types. Collections thereof are also supported.
* Non-inplace (copy-translation, default) always `tries` to return a collection of the same type, with all
  :attr:`IdTypes` converted to :py:class:`str`.
* In-place translation always returns ``None``, or raises :class:`~.dio.exceptions.NotInplaceTranslatableError`.

Overloads err on the overly-permissive side. Static type checkers (only MyPy is tested) may incorrectly allow things
like ``translator.translate("a-string-id")`` for ``int``-only ``Translator`` instances.

Limitations
-----------
Python does not support generics-of-generics, which is the primary domain in which the ``Translator.translate``-method
operates. See https://github.com/python/typing/issues/548 for details on this subject.

* Numpy is supported, but not typed.
* Pandas typing must be enabled using the ``ID_TRANSLATION_PANDAS_IS_TYPED``-flag.

.. code-block:: console

   pip install pandas-stubs
   mypy --always-true=ID_TRANSLATION_PANDAS_IS_TYPED /path/to/file.py

All ``pandas`` types will be ``None`` without stubs, which will break the overloads.
"""

import abc as _abc
import typing as _t
from collections import abc as _cabc
from typing import TYPE_CHECKING
from uuid import UUID as _UUID

ID: _t.Literal["id"] = "id"
"""Name of the ID placeholder in the translation :class:`~.Format`.

Cannot be changed (yet); see https://github.com/rsundqvist/id-translation/issues/151.
"""

IdTypes = int | str | _UUID
"""Type of the value being translated into human-readable labels."""
IdType = _t.TypeVar("IdType", bound=IdTypes)
"""Type variable bound by :attr:`IdTypes`."""

NameType = _t.TypeVar("NameType", bound=_cabc.Hashable)
"""Type used to label collections of IDs, such as the column names in a DataFrame or the keys of a dict."""

if TYPE_CHECKING:
    import pandas


CopyTranslatable: _t.TypeAlias = (
    # Scalar
    IdType
    |
    # Tuple
    tuple[IdType]
    | tuple[IdType, IdType]
    | tuple[IdType, IdType, IdType]
    | tuple[IdType, ...]
)

_InplaceTranslatable: _t.TypeAlias = list[IdType] | list[list[IdType]] | set[IdType]


# From CopyTranslatable
DictToId = dict[NameType, IdType]
DictToList = dict[NameType, list[IdType]]
DictToSet = dict[NameType, set[IdType]]
DictToOneTuple = dict[NameType, tuple[IdType]]
DictToTwoTuple = dict[NameType, tuple[IdType, IdType]]
DictToThreeTuple = dict[NameType, tuple[IdType, IdType, IdType]]
DictToVarTuple = dict[NameType, tuple[IdType, ...]]
DictTranslatable = (
    DictToId[NameType, IdType]
    | DictToList[NameType, IdType]
    | DictToSet[NameType, IdType]
    | DictToOneTuple[NameType, IdType]
    | DictToTwoTuple[NameType, IdType]
    | DictToThreeTuple[NameType, IdType]
    | DictToVarTuple[NameType, IdType]
)

PandasTranslatable = _t.Union["pandas.DataFrame", "pandas.Series", "pandas.Index"]

InplaceTranslatable: _t.TypeAlias = DictTranslatable[NameType, IdType] | _InplaceTranslatable[IdType]

Translatable: _t.TypeAlias = InplaceTranslatable[NameType, IdType] | CopyTranslatable[IdType] | PandasTranslatable
"""Enumeration of translatable types.

Types ``int``, ``str``, and ``UUID`` can be translated, or a collection thereof. Some :mod:`numpy` and :mod:`pandas`
types are also supported. The :class:`.Translator` is quite flexible when it comes to the encapsulating data structure,
and will do its best to return a data structure of the same type (albeit with elements converted to ``str``).

.. note::

   Dict values are always copied for translation.

   Setting ``copy=False`` merely controls whether the original dict is modified.
"""


SourceType = _t.TypeVar("SourceType", bound=_cabc.Hashable)
"""Type used to describe sources. Typically a string for things like files and database tables."""

NameToSource = dict[NameType, SourceType]
"""A mapping from name to source."""

NamesPredicate = _t.Callable[[NameType], bool]
"""A predicate type on names."""
NameTypes: _t.TypeAlias = NameType | _cabc.Iterable[NameType]
"""A union of a name type, or an iterable thereof."""
Names: _t.TypeAlias = NameTypes[NameType] | NamesPredicate[NameType]
"""Acceptable name types."""

TranslatableT = _t.TypeVar("TranslatableT", bound=Translatable[_t.Any, _t.Any])  # TODO: Higher-Kinded TypeVars
"""Simplified ``Translatable`` type."""


class HasSources(_abc.ABC, _t.Generic[SourceType]):
    """Indicates that `sources` and `placeholders` are available."""

    @property
    def sources(self) -> list[SourceType]:
        """A list of known Source names, such as ``cities`` or ``languages``."""
        return list(self.placeholders)

    @property
    @_abc.abstractmethod
    def placeholders(self) -> dict[SourceType, list[str]]:
        """Placeholders for all known Source names, such as ``id`` or ``name``.

        These are the (possibly unmapped) placeholders that may be used for translation.

        Returns:
            A dict ``{source: [placeholders..]}``.
        """
