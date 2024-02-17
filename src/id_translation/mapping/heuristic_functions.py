"""Functions which perform heuristics for score functions.

See Also:
    The :class:`~.HeuristicScore` class.
"""
from __future__ import annotations

import logging
import re
from typing import Any as _Any, Callable, Dict, Iterable, List, Set, Tuple, Union

VERBOSE: bool = False
LOGGER = logging.getLogger(__package__).getChild("verbose").getChild("heuristic_functions")


def like_database_table(
    name: str,
    tables: Iterable[str],
    context: _Any,
    *,
    plural_to_singular: bool | Dict[str, str] = True,
) -> Tuple[str, List[str]]:
    """Normalize `name` and `tables` to appear as base-form nouns.

    Args:
        name: A name to find a translation source.
        tables: Database tables used as possible translation sources.
        context: Ignored.
        plural_to_singular: Convert plural-form to singular form. Pass a ``dict`` to specify custom transformations,
            backed by the default transformer. See :class:`NounTransformer` for details. Set to ``False`` to disable.

    Returns:
        A tuple ``(normalized_name, normalized_table_names)``.

    See Also:
        * :func:`smurf_columns`

    Examples:
        Remove ID suffixes and convert a variety of plural forms to singular forms.

        >>> like_database_table("dog_id", ["dog", "dogs"], None)
        ('dog', ['dog', 'dog'])
        >>> like_database_table("city_ids", ["city", "cities"], None)
        ('city', ['city', 'city'])
        >>> like_database_table("CountryBitmask", ["Country", "COUNTRIES"], None)
        ('country', ['country', 'country'])

        Inputs are coerced to lower case.
    """
    to_singular = _make_noun_transformer(plural_to_singular)

    def _normalize_noun(noun: str) -> str:
        noun = noun.lower()
        noun = _strip_id_suffix(noun)
        noun = noun.replace("_", "")
        noun = noun.replace(".", "")
        noun = to_singular(noun)
        return noun

    return _normalize_noun(name), [_normalize_noun(t) for t in tables]


def smurf_columns(
    placeholder: str,
    columns: Iterable[str],
    table: str,
    *,
    plural_to_singular: bool | Dict[str, str] = False,
) -> Set[str]:
    """Short-circuit `placeholder` to a matching smurf column.

    The smurf naming convention (or anti-pattern, depending on who you ask) refers the practice of including the name
    of the table in the column name, especially for the primary key ID column.

    Typical columns one might encounter are ``country.country_id`` and ``cities.city_name``. Note that, for the latter
    match to be made, you must pass ``plural_to_singular=True | dict``.

    Special handling is implemented for ``placeholder="name"``, which will match when the singular-form table name is
    found in `columns`.

    Args:
        placeholder: A :class:`~id_translation.offline.Format` placeholder.
        columns: The columns of a database table.
        table: A ``Translator`` :attr:`source <id_translation.Translator.sources>` table to which
            the `columns` (or :attr:`~id_translation.Translator.placeholders`) belong.
        plural_to_singular: Convert plural-form to singular form. Pass a ``dict`` to specify custom transformations,
            backed by the default transformer. See :class:`NounTransformer` for details. Set to ``False`` to disable.

    Returns:
        A single-element set ``{column}``, iff a match is found. An empty set otherwise.

    Examples:
        Default translation :class:`~id_translation.offline.Format` (``{id}:{name}``) placeholders.

        >>> smurf_columns("id", ["city_id", "city_name", "city"], "city")
        {'city_id'}

        Both plural and singular form table names are supported, but the plural-to-singular transformation must be
        explicitly enabled with ``plural_to_singular=True``.

        >>> smurf_columns(
        ...   "name", ["city_id", "city_name"], "cities",
        ...   plural_to_singular=True)
        {'city_name'}

        Special handling for ``placeholder="name"`` when the table name is also a column.

        >>> smurf_columns("name", ["city_id", "city_name", "city"], "city")
        {'city'}

        As with any short-circuiting function, an empty set is returned when no match is found.

        >>> smurf_columns("id", ["dog_id", "bestie_name"], "bad_dogs")
        set()

        You may add custom mappings for irregular nouns.

        >>> smurf_columns(
        ...   "id", ["goose_id"], "geese",
        ...   plural_to_singular={"geese": "goose"})
        {'goose_id'}

    Notes:
        This function acts similarly to chained calls to :func:`value_fstring_alias`, using
        ``fstring="{context}", for_value="name"`` and ``fstring="{context}_{value}"``, but is more powerful since it is
        able to preprocess the inputs.

    See Also:
        * :func:`short_circuit`
        * :func:`like_database_table`
        * :func:`value_fstring_alias`
    """
    to_singular = _make_noun_transformer(plural_to_singular)
    table = to_singular(table.lower())

    placeholder = placeholder.lower()
    columns = {c.lower() for c in columns}

    if placeholder == "name" and table in columns:
        return {table}

    smurf = f"{table}_{placeholder}"
    for column in columns:
        if smurf == column.lower():
            return {smurf}

    return set()


def short_circuit(
    value: str,
    candidates: Set[str],
    context: _Any,
    *,
    value_regex: Union[str, re.Pattern[str]],
    target_candidate: str,
) -> Set[str]:
    """Short-circuit `value` to the target candidate if the target and regex conditions are met.

    If `target_candidate` is in `candidates` and `value` matches the given `value_regex`, a single-element set
    ``{target_candidate}`` is returned which will trigger short-circuiting in the calling ``Mapper``. If either of
    these conditions fail, an empty set is returned and the mapping procedure will continue.

    Args:
        value: A value to map.
        candidates: Candidates for `value`.
        context: Always ignored, exists for compatibility.
        value_regex: A pattern match against `value`. Case-insensitive by default.
        target_candidate: The candidate to short-circuit to.

    Returns:
        A single-element set ``{target_candidate}``, iff both conditions are met. An empty set otherwise.

    Examples:
        Always match any bite victim-columns to the `humans` table (see the :ref:`translation-primer` page).

        >>> short_circuit(
        ...   "first_bite_victim", {"humans", "animals"}, None,
        ...   value_regex=".*_bite_victim$", target_candidate="humans"
        ... )
        {'humans'}

        Short-circuiting will only trigger if the `value_regex` matches, and the `target_candidate` is present.
    """
    candidates = set(candidates)
    pattern = re.compile(value_regex, flags=re.IGNORECASE) if isinstance(value_regex, str) else value_regex

    if target_candidate not in candidates:
        LOGGER.getChild("short_circuit").debug(
            f"Short-circuiting failed for {value=}: The {target_candidate=} is an input candidate."
        )
        return set()

    if not pattern.match(value):
        LOGGER.getChild("short_circuit").debug(f"Short-circuiting failed for {value=}: Does not match {pattern=}.")
        return set()

    return {target_candidate}


def force_lower_case(value: str, candidates: Iterable[str], context: _Any) -> Tuple[str, List[str]]:
    """Force lower-case in `value` and `candidates`."""
    return value.lower(), [c.lower() for c in candidates]


def value_fstring_alias(
    value: str,
    candidates: Iterable[str],
    context: _Any,
    *,
    fstring: str,
    for_value: str = None,
    **kwargs: _Any,
) -> Tuple[str, Iterable[str]]:
    """Return a value formatted by `fstring`.

    .. note::

       This function modifies the `value`. Candidates are always returned as-is.

    Args:
        value: An element to find matches for.
        candidates: Potential matches for `value`. Not used (returned as given).
        context: Context in which the function is being called.
        fstring: The format string to use. Can use `value` and `context` as placeholders.
        for_value: If given, apply only if ``value == for_value``. When `for_value` is given, `fstring` arguments which
            do not use the `value` as a placeholder key are permitted.
        **kwargs: Additional keyword placeholders in `fstring`.

    Returns:
        A tuple ``(formatted_value, candidates)``.

    Raises:
        ValueError: If `fstring` does not contain a placeholder `'value'` and `for_value` is not given.

    Examples:
        Keys ``{value}`` and ``{context}`` are always available.

        >>> value_fstring_alias("id", ["dog_id"], "dog", fstring="{context}_{value}")
        ('dog_id', ['dog_id'])

        In cases such as these, consider using :func:`smurf_columns` instead, which will work both for ``table="dog"``
        (as above), and with ``table="dogs"``.
    """
    if not for_value and "{value}" not in fstring:
        # No longer a function of the value.
        raise ValueError(
            f"Invalid {fstring=} passed to value_fstring_alias(); does not contain {{value}}. "
            "To allow, the 'for_value' parameter must be given as well."
        )

    if for_value and value != for_value:
        return value, candidates

    return fstring.format(value=value, context=context, **kwargs), candidates


def candidate_fstring_alias(
    value: str,
    candidates: Iterable[str],
    context: _Any,
    *,
    fstring: str,
    **kwargs: _Any,
) -> Tuple[str, Iterable[str]]:
    """Return candidates formatted by `fstring`.

    .. note::

       This function modifies the `candidates`. The `value` is always returned as-is.

    Args:
        value: An element to find matches for. Not used (returned as given).
        candidates: Potential matches for `value`.
        context: Context in which the function is being called.
        fstring: The format string to use. Can use `value`, `context`, and elements of `candidates` as placeholders.
        **kwargs: Additional keyword placeholders in `fstring`.

    Returns:
        A tuple ``(value, formatted_candidates)``.

    Raises:
        ValueError: If `fstring` does not contain a placeholder `'candidate'`.
    """
    if "{candidate}" not in fstring:
        raise ValueError(f"Invalid {fstring=} passed to candidate_fstring_alias(); does not contain {{candidate}}.")

    return value, [fstring.format(value=value, candidate=c, context=context, **kwargs) for c in candidates]


def _strip_id_suffix(string: str) -> str:
    for suffix in "id", "ids", "bitmask":
        sz = len(suffix)
        if len(string) > sz and string.endswith(suffix):
            string = string[:-sz]

    if string.endswith("_"):
        string = string[:-1]

    return string


class NounTransformer:
    """Naive utility class for transforming nouns to singular form.

    This class performs simple heuristics to convert nouns commonly used as database table names. It will quickly break
    either if given nouns that are already on singular form, or are not trivially convertible (see
    :attr:`PLURAL_TO_SINGULAR_SUFFIXES`) to singular form.

    Examples:
        >>> nt = NounTransformer(custom={"geese": "goose"})
        >>> nt("city"), nt("cities")
        ('city', 'city')
        >>> nt("country"), nt("countries")
        ('country', 'country')
        >>> nt("geese"), nt("goose"), nt("species")
        ('goose', 'goose', 'species')

        May break when given a noun that is already singular.

        >>> nt("bus"), nt("news")
        ('bu', 'new')

        See :attr:`PLURAL_TO_SINGULAR_SUFFIXES` for affected suffixes.
    """

    IRREGULARS: Dict[str, str] = {
        "species": "species",
    }
    """Known irregular plural-to-singular transformations."""

    # https://wordtoolbox.com/nouns-ending-with/<letter-combination>
    PLURAL_TO_SINGULAR_SUFFIXES: Tuple[Tuple[str, str], ...] = (
        ("ies", "y"),  # cities -> city
        ("es", ""),  # irises -> iris, and many others
        ("s", ""),  # catch-all
    )
    """Plural-to-singular suffix mappings."""

    def __init__(self, custom: Dict[str, str]) -> None:
        self._pre = {**self.IRREGULARS, **custom}

    def __call__(self, noun: str) -> str:
        """Convert to singular form."""
        singular = self._pre.get(noun)
        return self._to_singular(noun) if singular is None else singular

    @classmethod
    def _to_singular(cls, plural: str) -> str:
        for suffix, replacement in cls.PLURAL_TO_SINGULAR_SUFFIXES:
            if plural.endswith(suffix):
                return plural[: -len(suffix)] + replacement
        return plural


def _make_noun_transformer(plural_to_singular: bool | Dict[str, str]) -> Callable[[str], str]:
    """Returns a NOOP if `plural_to_singular` is ``False``."""
    if plural_to_singular is False:
        return lambda noun: noun

    if plural_to_singular is True:
        plural_to_singular = {}
    return NounTransformer(plural_to_singular)
