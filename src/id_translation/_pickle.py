"""Pickling of :class:`~id_translation.Translator` snapshots.

Snapshots are same-version artifacts by definition: ``ConfigMetadata`` records the ``id-translation`` version and
``use_cached()`` refuses any mismatch, so there is no cross-version repair. ``load_persistent_instance`` rejects a
foreign snapshot before reading it, but ``Translator.restore`` is handed a path and cannot. A pickled ``Translator``
therefore carries its version twice:

* As the argument of :func:`unpickle_translator`, which pickle calls before it unpickles the state. The version is
  checked before any nested object from another version can fail with an unrelated error.
* In the state, for ``Translator.__setstate__``: pickle restores a snapshot from before the version stamp without
  :func:`unpickle_translator`.
"""

import pickle
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._translator import Translator

VERSION_KEY = "_id_translation_version"  # Pickled state key; never an attribute.


def unpickle_translator(cls: "type[Translator[Any, Any, Any]]", version: str) -> "Translator[Any, Any, Any]":
    """Create an empty `cls` for pickle to fill. Pickles refer to this function by name: do not move or rename it."""
    check_version(version, cls)
    return cls.__new__(cls)


def stamp(state: Any) -> Any:
    version = current_version()
    if isinstance(state, tuple):  # A subclass with `__slots__`; `object.__getstate__` returns `(dict, slots)`.
        return {**(state[0] or {}), VERSION_KEY: version}, state[1]
    return {**state, VERSION_KEY: version}


def unstamp(state: Any, cls: type) -> tuple[dict[str, Any], dict[str, Any]]:
    slots: dict[str, Any] = {}
    if isinstance(state, tuple):  # A subclass with `__slots__`; `object.__getstate__` returns `(dict, slots)`.
        state, slots = state[0] or {}, state[1] or {}

    state = dict(state)
    check_version(state.pop(VERSION_KEY, None), cls)
    return state, slots


def check_version(version: str | None, cls: type) -> None:
    if version != (running := current_version()):
        written = "an unknown version (before 2.0.0)" if version is None else f"version {version}"
        exc = pickle.UnpicklingError(f"Snapshot was written by {written} of id-translation, not {running}.")
        exc.add_note(f"Hint: Recreate it with {cls.__name__}.go_offline(path=...).")
        raise exc


def current_version() -> str:
    from id_translation import __version__  # noqa: PLC0415  # The package imports Translator before defining it.

    return __version__
