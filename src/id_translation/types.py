"""Types used for translation.

Rules of thumb
--------------
* The :attr:`IdTypes` are the only `"truly"` translatable types. Collections thereof are also supported.
* Non-inplace (copy-translation, default) always `tries` to return a collection of the same type, with all
  :attr:`IdTypes` converted to :py:class:`str`.
* In-place translation always returns ``None``, or raises :class:`~.dio.exceptions.NotInplaceTranslatableError`.
* When ``default_fmt=None``, IDs may be replaced by ``None`` as well (contrary to type hints).
* Translating with ``maximal_untranslated_fraction=0`` guarantees that IDs are never replaced with ``None``.

Overloads err on the overly-permissive side. Static type checkers (only MyPy is tested) may incorrectly allow things
like ``translator.translate("a-string-id")`` for ``int``-only ``Translator`` instances.

Limitations
-----------
Python does not support generics-of-generics, which is the primary domain in which the ``Translator.translate``-method
operates. See https://github.com/python/typing/issues/548 for details on this subject.

* Reverse-mode translation (``reverse=True``) is not type-hinted.
* Numpy is supported, but not typed.
* Pandas typing must be enabled using the ``ID_TRANSLATION_PANDAS_IS_TYPED``-flag.

.. code-block:: console

   pip install pandas-stubs
   mypy --always-true=ID_TRANSLATION_PANDAS_IS_TYPED /path/to/file.py

All ``pandas`` types will be ``None`` without stubs, which will break the overloads.
"""
import abc as _abc
import typing as _type
from typing import TYPE_CHECKING
from uuid import UUID as _UUID

ID: str = "id"
"""Name of the ID placeholder."""

IdTypes = _type.Union[int, str, _UUID]
"""Type of the value being translated into human-readable labels."""
IdType = _type.TypeVar("IdType", bound=IdTypes)
"""Type variable bound by :attr:`IdTypes`."""

NameType = _type.TypeVar("NameType", bound=_type.Hashable)
"""Type used to label collections of IDs, such as the column names in a DataFrame or the keys of a dict."""

if TYPE_CHECKING:
    import pandas


CopyTranslatable = _type.Union[
    # Scalar
    IdType,
    # Tuple
    _type.Tuple[IdType],
    _type.Tuple[IdType, IdType],
    _type.Tuple[IdType, IdType, IdType],
    _type.Tuple[IdType, ...],
]

_InplaceTranslatable = _type.Union[
    _type.List[IdType],
    _type.List[_type.List[IdType]],
    _type.Set[IdType],
]


# From CopyTranslatable
DictToId = _type.Dict[NameType, IdType]
DictToList = _type.Dict[NameType, _type.List[IdType]]
DictToSet = _type.Dict[NameType, _type.Set[IdType]]
DictToOneTuple = _type.Dict[NameType, _type.Tuple[IdType]]
DictToTwoTuple = _type.Dict[NameType, _type.Tuple[IdType, IdType]]
DictToThreeTuple = _type.Dict[NameType, _type.Tuple[IdType, IdType, IdType]]
DictToVarTuple = _type.Dict[NameType, _type.Tuple[IdType, ...]]
DictTranslatable = _type.Union[
    DictToId[NameType, IdType],
    DictToList[NameType, IdType],
    DictToSet[NameType, IdType],
    DictToOneTuple[NameType, IdType],
    DictToTwoTuple[NameType, IdType],
    DictToThreeTuple[NameType, IdType],
    DictToVarTuple[NameType, IdType],
]
PandasTranslatable = _type.Union["pandas.DataFrame", "pandas.Series", "pandas.Index"]

InplaceTranslatable = _type.Union[
    DictTranslatable[NameType, IdType],
    _InplaceTranslatable[IdType],
]

Translatable = _type.Union[InplaceTranslatable[NameType, IdType], CopyTranslatable[IdType], PandasTranslatable]
"""Enumeration of translatable types.

Types ``int``, ``str``, and ``UUID`` can be translated, or a collection thereof. Some :mod:`numpy` and :mod:`pandas`
types are also supported. The :class:`.Translator` is quite flexible when it comes to the encapsulating data structure,
and will do its best to return a data structure of the same type (albeit with elements converted to ``str``).

.. note::

   Dict values are always copied for translation.

   Setting ``inplace=True`` merely controls whether the original dict is modified.
"""


SourceType = _type.TypeVar("SourceType", bound=_type.Hashable)
"""Type used to describe sources. Typically a string for things like files and database tables."""

NameToSource = _type.Dict[NameType, SourceType]
"""A mapping from name to source."""

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
