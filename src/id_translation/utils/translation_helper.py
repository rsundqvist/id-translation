"""Utility for single-purpose translation tasks.

Examples:
    Implementing a function with a ``translate`` arg using the helper class.

    **Initialization**

    Typically, you'd use something like a :meth:`id_translation.Translator.from_config` callback with suitable
    arguments. For our purposes however, dummy translations are enough.

    >>> from id_translation import Translator
    >>> helper = TranslationHelper[str, str, int](
    ...     Translator,
    ...     "translate",  # for error messages
    ...     names="name",  # fixed translation argument
    ... )
    >>> helper
    TranslationHelper(id_translation.Translator, names='name')

    The `user_params_name='translate'` argument is not printed because it's the default.

    **Function definition**

    Arguments provided when the helper is initialized are fixed. An exception is raised if fixed arguments overlap
    either with `user_kwargs`, or with the defaults provided as keyword-arguments to :meth:`~.TranslationHelper.apply`.

    In the example below, ``names="name"`` is a fixed argument and ``fmt="{id}:{name}"`` is a default argument. The
    `translatable` (= ``list(range(n))``) and `inplace` arguments are always required, but cannot be defined as fixed arguments.
    The reasons for this are mostly related to the use of :py:func:`typing.overload`.

    >>> def example(
    ...     n: int,
    ...     *,
    ...     translate: UserParams[str, str, int] = True,
    ... ) -> list[str]:
    ...     items: list[str] = helper.apply(
    ...         list(range(n)),
    ...         inplace=False,  # required
    ...         user_params=translate,  # forwarded
    ...         fmt="{id}:{name}",  # default - user params can override
    ...     )
    ...     return items

    Let's take our new function for a spin.

    **Basic usage**

    When ``user_params = translate = True``, default settings are used.

    >>> example(1)
    ['0:name-of-0']

    Translation may be disabled by passing ``False``, making the helper return immediately.

    >>> example(2, translate=False)
    [0, 1]

    Note the output is of type ``list[int]``, rather than expected ``list[str]``, in this case.

    .. seealso:: The :envvar:`ID_TRANSLATION_DISABLED` environment variable.

    Aside from the obvious ``true|false`` behaviour, the :func:`TranslationHelper` may also act on the input type. The
    helper can be configured what input that the user may pass; see the `fixed_params` argument of the class. Use
    :meth:`.TranslationHelper.convert_user_params` to validate the configuration.

    **Argument forwarding**

    Dicts are interpreted as keyword-arguments for :meth:`.Translator.translate`.

    >>> example(22, translate={"fmt": "{name} (binary={id:0b})"})[-1]
    'name-of-21 (binary=10101)'

    Plain strings are interpreted as a temporary translation :class:`~id_translation.offline.Format`.

    >>> example(22, translate="{name} (binary={id:0b})")[-1]
    'name-of-21 (binary=10101)'

    This is equivalent to passing ``translate={"fmt": "{name} (binary={id:0b})"}``, as we did above.

    **Documenting user arguments**

    Initialized helpers provide methods creating :meth:`user_params <.make_user_params_docstring>`
    and :meth:`type error <.make_type_error_docstring>` docstrings, which may be used as part of the docstring of
    functions that use translation helpers.

    >>> example.__doc__.format(  # Doctest: +SKIP
    ...     translate=helper.make_user_params_docstring(),
    ...     type_error=helper.make_type_error_docstring(),
    ... )
    >>> help(example)

    See the :func:`example` function below for output.
"""

import os as _os
import typing as _t

from id_translation import Translator as _Translator
from id_translation import translator_typing as _trt
from id_translation import types as _tt
from id_translation.offline import types as _ot
from id_translation.types import TranslatableT

MaximalUntranslatedFractionTypes = int | float
UserParams = (
    bool
    | _ot.FormatType
    | MaximalUntranslatedFractionTypes
    | _trt.TranslateParams[_tt.NameType, _tt.SourceType, _tt.IdType]
)

FactoryFn = _t.Callable[[], _Translator[_tt.NameType, _tt.SourceType, _tt.IdType]]
FactoryTypes = (
    FactoryFn[_tt.NameType, _tt.SourceType, _tt.IdType] | _Translator[_tt.NameType, _tt.SourceType, _tt.IdType]
)

ALWAYS_RESERVED = ("inplace", "translatable")


class TranslationHelper(_t.Generic[_tt.NameType, _tt.SourceType, _tt.IdType]):
    """Helper class for single-purpose translation tasks.

    **Typing rules**

    Compared to :meth:`.Translator.translate`, typing is limited. Rules for :meth:`.TranslationHelper.apply`:

        * When ``user_params=False``, output= input.
        * When ``user_params != False``, output= ``Any`` (new variable) or same (existing variable).
        * When ``inplace=True``, output= ``None``.

    Note that ``user_params=False`` always takes precedence, as the translation process is aborted without any
    ``Translator`` involvement.

    Args:
        translator_or_factory: A callable ``() -> Translator`` or an initialized :class:`.Translator`.
        user_params_name: Used for reporting errors.
        **fixed_params: Fixed parameters for :meth:`.Translator.translate`. Attempting to override these in
            :meth:`TranslationHelper.apply` will raise an error.

    See Also:
        If you are using the https://github.com/rsundqvist/id-translation-project/ template, there are several
        namespace-functions which may be suitable :class:`.Translator` suppliers.

    * {sample_functions}

    Links lead to the generated documentation for the {sample_namespace} sample project.
    """

    def __init__(
        self,
        translator_or_factory: FactoryTypes[_tt.NameType, _tt.SourceType, _tt.IdType],
        user_params_name: str = "translate",
        **fixed_params: _t.Unpack[_trt.TranslateParams[_tt.NameType, _tt.SourceType, _tt.IdType]],
    ) -> None:
        self._user_params_name = user_params_name
        self._get: FactoryFn[_tt.NameType, _tt.SourceType, _tt.IdType]

        if isinstance(translator_or_factory, _Translator):
            self._get = lambda: translator_or_factory
        else:
            self._get = translator_or_factory

        self._fixed = self._validate("fixed_params", fixed_params, protected=self._make())
        self._translated_names: _tt.NameToSource[_tt.NameType, _tt.SourceType] | None = None

    @_t.overload
    def apply(
        self,
        translatable: TranslatableT,
        *,
        user_params: UserParams[_tt.NameType, _tt.SourceType, _tt.IdType],
        inplace: _t.Literal[True],
        **default_params: _t.Unpack[_trt.TranslateParams[_tt.NameType, _tt.SourceType, _tt.IdType]],
    ) -> None: ...

    @_t.overload
    def apply(
        self,
        translatable: TranslatableT,
        *,
        inplace: _t.Literal[False] = False,
        user_params: _t.Literal[False],
        **default_params: _t.Unpack[_trt.TranslateParams[_tt.NameType, _tt.SourceType, _tt.IdType]],
    ) -> TranslatableT: ...

    @_t.overload
    def apply(
        self,
        translatable: TranslatableT,
        *,
        inplace: _t.Literal[False] = False,
        user_params: UserParams[_tt.NameType, _tt.SourceType, _tt.IdType],
        **default_params: _t.Unpack[_trt.TranslateParams[_tt.NameType, _tt.SourceType, _tt.IdType]],
    ) -> _t.Any: ...

    def apply(
        self,
        translatable: TranslatableT,
        *,
        inplace: bool = False,
        user_params: UserParams[_tt.NameType, _tt.SourceType, _tt.IdType],
        **default_params: _t.Unpack[_trt.TranslateParams[_tt.NameType, _tt.SourceType, _tt.IdType]],
    ) -> _t.Any | None:
        """Apply translation to `translatable`.

        Keys {always_reserved} are always reserved.

        Args:
            translatable: A data structure to translate.
            inplace: If ``True``, translate in-place and return ``None``.
            user_params: {user_params}
            **default_params: Default arguments for the ``translate`` method. May be overridden by `user_params`. If the
                user passes any reserved or fixed keys, a :class:`TypeError` is raised.

        Returns:
            The original `translatable` if `user_params` is ``False``. Otherwise, return a translated copy or
            ``None`` based on the `inplace`-setting (see :meth:`.Translator.translate`).

        Raises:
            TypeError: If reserved or fixed keys are passed in the `user_params`.
        """
        return self._apply(translatable, inplace=inplace, user_params=user_params, default_params=default_params)

    def _apply(
        self,
        translatable: TranslatableT,
        *,
        inplace: bool,
        user_params: UserParams[_tt.NameType, _tt.SourceType, _tt.IdType],
        default_params: _trt.TranslateParams[_tt.NameType, _tt.SourceType, _tt.IdType],
    ) -> _t.Any:
        try:
            params = self._process_params(user_params=user_params, default_params=default_params)
        except _AbortTranslation:
            return None if inplace else translatable
        _t.assert_type(params, _trt.TranslateParams[_tt.NameType, _tt.SourceType, _tt.IdType])

        translator = self.get_translator()
        result = translator.translate(translatable, inplace=inplace, **params)  # type: ignore[call-overload]

        self._translated_names = translator.translated_names(with_source=True)
        return result

    def name_to_source(self) -> _tt.NameToSource[_tt.NameType, _tt.SourceType]:
        """Return the name-to-source mapping of the latest :meth:`.apply()`-call."""
        if self._translated_names is None:
            raise ValueError("No names have been translated using this TranslationHelper.")
        return dict(self._translated_names)

    def _process_params(
        self,
        *,
        user_params: UserParams[_tt.NameType, _tt.SourceType, _tt.IdType],
        default_params: _trt.TranslateParams[_tt.NameType, _tt.SourceType, _tt.IdType],
    ) -> _trt.TranslateParams[_tt.NameType, _tt.SourceType, _tt.IdType]:
        self._validate("default_params", default_params)

        if user_params is False:
            # Indicates that no translation should be performed. We could perform this check right away and possibly
            # save some time on validating the default parameters. Reason that we don't is two-fold: 1) It may hide a
            # configuration error, and 2) it is assumed that translation is the most common use case.
            raise _AbortTranslation

        converted_user_params = self.convert_user_params(user_params, validate=False)
        self._validate(self._user_params_name, converted_user_params)

        return {**default_params, **converted_user_params, **self._fixed}

    def convert_user_params(
        self,
        user_params: UserParams[_tt.NameType, _tt.SourceType, _tt.IdType],
        validate: bool = True,
    ) -> _trt.TranslateParams[_tt.NameType, _tt.SourceType, _tt.IdType]:
        """Convert user parameters.

        Args:
            user_params: End-user parameters.
            validate: If ``False``, skip the regular fixed parameter validation.

        Returns:
            Valid :meth:`.Translator.translate` parameters
        """
        if user_params is False:
            msg = f"Cannot convert {self._user_params_name}=False."
            raise TypeError(msg)

        if user_params is True:
            return self._make()

        if isinstance(user_params, str):
            return self._make(fmt=user_params)

        if isinstance(user_params, _t.get_args(MaximalUntranslatedFractionTypes)):
            return self._make(maximal_untranslated_fraction=user_params)

        if isinstance(user_params, dict):
            params = self._make(**user_params)
            return self._validate(self._user_params_name, params) if validate else params

        types = (typ.__name__ for typ in (bool, str, float, dict))
        msg = f"type({self._user_params_name}) is {type(user_params).__name__}. Expected: ({', '.join(types)})."
        raise TypeError(msg)

    @classmethod
    def _make(
        cls, **params: _t.Unpack[_trt.TranslateParams[_tt.NameType, _tt.SourceType, _tt.IdType]]
    ) -> _trt.TranslateParams[_tt.NameType, _tt.SourceType, _tt.IdType]:
        """Convenience function to avoid having to repeat the type variables."""
        return params

    def get_translator(self) -> _Translator[_tt.NameType, _tt.SourceType, _tt.IdType]:
        """Return a ``Translator`` instance."""
        return self._get()

    def __repr__(self) -> str:
        from rics.misc import format_kwargs, get_public_module

        parts = [get_public_module(self._get, include_name=True, resolve_reexport=True)]

        if self._fixed:
            parts.append(format_kwargs(self._fixed))

        if (user_param_name := self._user_params_name) != "translate":
            parts.append(f"{user_param_name=}")

        return f"{type(self).__name__}({', '.join(parts)})"

    def _validate(
        self,
        name: str,
        params: _trt.TranslateParams[_tt.NameType, _tt.SourceType, _tt.IdType],
        *,
        protected: _trt.TranslateParams[_tt.NameType, _tt.SourceType, _tt.IdType] | None = None,
    ) -> _trt.TranslateParams[_tt.NameType, _tt.SourceType, _tt.IdType]:
        if keys := {*(self._fixed if protected is None else protected), *ALWAYS_RESERVED}.intersection(params):
            msg = f"Found protected {keys=} in {name}={params}."
            raise TypeError(msg)

        return params

    def make_user_params_docstring(self) -> str:
        """Create description for `user_params`.

        Example output below.

        Args:
            user_params: {user_params}

        Output may vary depending on helper settings.
        """
        reserved = set(self._fixed)

        parts = [
            "Translation options. Set to ``False`` to disable (``True`` = use defaults).",
            "If :class:`dict`, use as keyword-arguments for :attr:`.Translator.translate` (raises"
            f" :py:class:`TypeError` for {len(reserved) + len(ALWAYS_RESERVED)} reserved keys).",
        ]

        types = [
            (str, "fmt", "see :class:`.Format`"),
            (float, "maximal_untranslated_fraction", "where 0=disable check, 1=no missing IDs allowed"),
        ]

        type_parts = []
        for typ, key, hint in types:
            if key in reserved:
                continue

            template = ":class:`{.__name__}` = ``{!r}`` ({})"
            type_parts.append(template.format(typ, key, hint))

        if type_parts:
            parts.append("Other types:")
            parts.append(", ".join(type_parts) + ".")

        return " ".join(parts)

    def make_type_error_docstring(self) -> str:
        """Create description for ``TypeError``.

        Example output below.

        Raises:
            TypeError: {type_error}

        Output may vary depending on helper settings.
        """
        reserved = *ALWAYS_RESERVED, *self._fixed

        parts = (
            f"Raised if `{self._user_params_name}` is a ``dict`` containing any of the {len(reserved)} the reserved keys: ",
            ", ".join(f"``'{key}'``" for key in reserved),
            ".",
        )
        return "".join(parts)

    def make_docstrings(
        self,
        *,
        user_params_key: str | None = None,
        type_error_key: str = "type_error",
    ) -> dict[str, str]:
        """Convenience method for creating multiple docstrings.

        Args:
            user_params_key: Key for :meth:`make_user_params_docstring` output. Default is `user_params_name`.
            type_error_key: Key for :meth:`make_type_error_docstring` output.

        Returns:
            A dict of docstrings.
        """
        return {
            self._user_params_name if user_params_key is None else user_params_key: self.make_user_params_docstring(),
            type_error_key: self.make_type_error_docstring(),
        }


def _patch_docstrings() -> None:
    functions = "get_singleton", "create_translator", "load_cached_translator"
    index = "https://rsundqvist.github.io/id-translation-project/index.html"
    template = "`{{namespace}}.id_translation.{func}() <{index}#big_corporation_inc.id_translation.{func}>`_"

    cls = TranslationHelper

    assert cls.__doc__, "missing docstring"  # noqa S101
    cls.__doc__ = cls.__doc__.format(
        sample_namespace=f"`Big Corporation Inc. <{index}>`_",
        sample_functions="\n    * ".join(template.format(func=func, index=index) for func in functions),
    )

    dummy: TranslationHelper[str, str, str] = cls(_Translator, user_params_name="<user_params_name>")

    docstrings = {
        "always_reserved": ", ".join(f"``'{key}'``" for key in ALWAYS_RESERVED),
        **dummy.make_docstrings(user_params_key="user_params"),
    }

    for func in cls.apply, cls.make_user_params_docstring, cls.make_type_error_docstring:
        assert func.__doc__, "missing docstring"  # noqa S101
        func.__doc__ = func.__doc__.format_map(docstrings)


_patch_docstrings()


if _os.environ.get("SPHINX_BUILD") == "true":  # pragma: no cover
    helper = TranslationHelper[str, str, int](_Translator, "translate", names="name")

    def example(
        n: int,
        *,
        translate: UserParams[str, str, int] = True,
    ) -> list[str]:
        """Create and translate the first `n` integers.

        Docstrings for `translate` and ``TypeError`` were produced by :meth:`~.TranslationHelper.make_docstrings`.

        Args:
            n: Number of integers to create.
            translate: {translate}

        Raises:
            TypeError: {type_error}

        Returns:
            A list.
        """
        items: list[str] = helper.apply(
            list(range(n)),
            inplace=False,
            user_params=translate,
            fmt="{id}:{name}",
        )
        return items

    example.__doc__ = example.__doc__.format(  # type: ignore[union-attr]
        translate=helper.make_user_params_docstring(),
        type_error=helper.make_type_error_docstring(),
    )


class _AbortTranslation(Exception):  # noqa: N818
    pass
