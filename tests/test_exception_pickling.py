"""Every exception and warning survives pickle and copy, so it can cross process boundaries and ``deepcopy``.

``BaseException`` reduces to ``(cls, self.args, self.__dict__)``, so reconstruction calls ``cls(msg)``. Any class whose
constructor needs more than the message breaks on the way back. Classes with a ``for_*`` factory are also checked as
built by it, since the factory is what fills in the data attributes.
"""

import copy
import importlib
import inspect
import pickle
import pkgutil
from collections.abc import Callable, Iterator
from types import ModuleType
from typing import TypeVar

import pytest

import id_translation
from id_translation.dio.exceptions import NotInplaceTranslatableError, UntranslatableTypeError
from id_translation.exceptions import TooManyFailedTranslationsError
from id_translation.fetching import MemoryFetcher
from id_translation.fetching.exceptions import (
    ConcurrentOperationWarning,
    DuplicateSourceError,
    ForbiddenOperationError,
    UnknownPlaceholderError,
    UnknownSourceError,
)
from id_translation.mapping.exceptions import (
    AmbiguousScoreError,
    ScoringDisabledError,
    UnmappedExplicitNamesError,
    UnmappedValuesError,
    UserMappingError,
)
from id_translation.mapping.score_functions import disabled
from id_translation.offline import Format
from id_translation.offline.parse_format_string import BadDelimiterError


def _modules() -> Iterator[ModuleType]:
    # The walk yields submodules only. It never reaches its own `onerror`: each package is imported here first.
    yield id_translation
    for info in pkgutil.walk_packages(id_translation.__path__, prefix="id_translation."):
        try:
            yield importlib.import_module(info.name)
        except Exception as e:
            pytest.fail(f"Cannot import {info.name!r} ({e!r}); the walk would silently skip any exceptions it defines.")


def _exception_classes() -> list[type[BaseException]]:
    found: dict[type[BaseException], None] = {}
    for module in _modules():
        for obj in vars(module).values():
            if isinstance(obj, type) and issubclass(obj, BaseException) and obj.__module__ == module.__name__:
                found[obj] = None
    return sorted(found, key=lambda c: f"{c.__module__}.{c.__qualname__}")


def _factory_names(cls: type[BaseException]) -> list[str]:
    # Includes inherited factories, so a subclass of a class with a factory needs its own sample.
    names = []
    for name in dir(cls):
        attr = inspect.getattr_static(cls, name)
        if not name.startswith("for_") or not (callable(attr) or isinstance(attr, classmethod)):
            continue
        if not isinstance(attr, classmethod):
            pytest.fail(f"{cls.__qualname__}.{name} must be a classmethod, so that subclasses construct themselves.")
        names.append(name)
    return names


E = TypeVar("E", bound=BaseException)


def _raised(cls: type[E], func: Callable[[], object]) -> E:
    with pytest.raises(cls) as exc_info:
        func()
    return exc_info.value


_FETCHER: MemoryFetcher[str, int] = MemoryFetcher(
    {"source": {"id": [1], "name": ["one"]}}, identifiers=["fetchers.toml"]
)

FACTORY_SAMPLES: dict[str, Callable[[], BaseException]] = {
    "ConcurrentOperationWarning.for_operation": lambda: ConcurrentOperationWarning.for_operation(
        "initialize_sources", fetcher_class="SqlFetcher"
    ),
    "ForbiddenOperationError.for_operation": lambda: ForbiddenOperationError.for_operation(
        "FETCH_ALL", fetcher_class="SqlFetcher", hints="Check it."
    ),
    "UnknownPlaceholderError.for_placeholders": lambda: UnknownPlaceholderError.for_placeholders(
        "id", placeholders=["key", "name"], source="source", caller=_FETCHER, hints="Check it."
    ),
    "UnknownSourceError.for_sources": lambda: UnknownSourceError.for_sources({"x"}, sources={"source"}),
    # A type that pickle cannot find by name.
    "NotInplaceTranslatableError.for_translatable": lambda: NotInplaceTranslatableError.for_translatable({}.keys()),
}

DATA_SAMPLES: dict[str, Callable[[], BaseException]] = {
    "UnmappedExplicitNamesError": lambda: UnmappedExplicitNamesError("msg", names=["a", "b"], unmapped=["b"]),
    "UserMappingError": lambda: UserMappingError("msg", value="a", candidates=["b"]),
    "ScoringDisabledError": lambda: _raised(
        ScoringDisabledError, lambda: disabled("name", ["id", "name"], "source", strict=True)
    ),
    "AmbiguousScoreError": lambda: AmbiguousScoreError("msg", hints="Check it."),
    "UntranslatableTypeError": lambda: UntranslatableTypeError("msg", hints="Check it."),
    "BadDelimiterError": lambda: _raised(BadDelimiterError, lambda: Format("{a}]")),
    "TooManyFailedTranslationsError": lambda: TooManyFailedTranslationsError(
        "msg", name="n", source="s", n_untranslated=1, n_total=2, max_fails=0.5, sample_ids=[7]
    ),
    "DuplicateSourceError": lambda: DuplicateSourceError("msg", source="s", hints="Check it."),
    "UnmappedValuesError": lambda: UnmappedValuesError("msg", unmapped=["a"]),
}

CLONES: dict[str, Callable[[BaseException], BaseException]] = {
    "pickle": lambda exc: pickle.loads(pickle.dumps(exc)),  # noqa: S301
    "copy": copy.copy,
    "deepcopy": copy.deepcopy,
}


def _assert_round_trip(exc: BaseException, clone: Callable[[BaseException], BaseException]) -> None:
    actual = clone(exc)
    assert type(actual) is type(exc)
    assert actual.args == exc.args
    assert str(actual) == str(exc)
    assert getattr(actual, "__notes__", None) == getattr(exc, "__notes__", None)
    assert actual.__dict__ == exc.__dict__


def test_walk_found_classes() -> None:
    assert len(_exception_classes()) > 20, "walk found too few classes; is the package layout intact?"


@pytest.mark.parametrize("clone", CLONES.values(), ids=CLONES.keys())
@pytest.mark.parametrize("cls", _exception_classes(), ids=lambda c: c.__qualname__)
def test_message_only(cls: type[BaseException], clone: Callable[[BaseException], BaseException]) -> None:
    _assert_round_trip(cls("msg"), clone)


@pytest.mark.parametrize("clone", CLONES.values(), ids=CLONES.keys())
@pytest.mark.parametrize(
    "make", [*FACTORY_SAMPLES.values(), *DATA_SAMPLES.values()], ids=[*FACTORY_SAMPLES, *DATA_SAMPLES]
)
def test_with_data(make: Callable[[], BaseException], clone: Callable[[BaseException], BaseException]) -> None:
    _assert_round_trip(make(), clone)


def test_every_factory_has_a_sample() -> None:
    factories = {f"{cls.__qualname__}.{name}" for cls in _exception_classes() for name in _factory_names(cls)}
    assert sorted(factories - FACTORY_SAMPLES.keys()) == [], "add a FACTORY_SAMPLES entry for each"
    assert sorted(FACTORY_SAMPLES.keys() - factories) == [], "stale FACTORY_SAMPLES entries"


def test_bare_string_is_one_item() -> None:
    assert TooManyFailedTranslationsError("msg", sample_ids="abc").sample_ids == ("abc",)


def test_not_inplace_type_name() -> None:
    import pandas as pd

    unimportable = type("Unimportable", (), {"__module__": "nonexistent.mod"})

    series = pd.Series([1], index=["func"])
    assert NotInplaceTranslatableError.for_translatable(series).translatable_type == "pandas.Series"
    assert NotInplaceTranslatableError.for_translatable({}.keys()).translatable_type == "builtins.dict_keys"
    assert NotInplaceTranslatableError.for_translatable(unimportable()).translatable_type == (
        "nonexistent.mod.Unimportable"
    )
