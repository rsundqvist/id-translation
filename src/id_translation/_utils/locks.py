from _thread import RLock, get_ident
from contextlib import AbstractContextManager, nullcontext
from typing import Any

from rics.env.read import read_bool

DISABLE_LOCKS = "ID_TRANSLATION_DISABLE_LOCKS"


class CloneSafeLock(RLock):  # type: ignore[misc]  # Final in typeshed, but subclassable.
    """A ``threading.RLock`` that deep-copies and pickles as a new, released one.

    A subclass of the C type, not a wrapper, so that ``with`` enters and exits in C: an interrupt such as
    ``KeyboardInterrupt`` then has the fewest bytecodes in which to leave it held. A lock left held that way blocks other
    threads on its object until that object is recreated; the interrupted thread can still use it.
    """

    def __deepcopy__(self, memo: dict[int, Any]) -> "CloneSafeLock":
        return CloneSafeLock()

    def __reduce__(self) -> tuple[type["CloneSafeLock"], tuple[()]]:
        return CloneSafeLock, ()


def new_lock() -> AbstractContextManager[Any]:
    """Return a :class:`CloneSafeLock`, or a no-op if the undocumented ``ID_TRANSLATION_DISABLE_LOCKS`` is set.

    Read once per lock, so that every exit matches its enter. Strict, like ``ID_TRANSLATION_DISABLED``: a typo raises
    instead of silently leaving locks on.
    """
    return nullcontext() if read_bool(DISABLE_LOCKS) else CloneSafeLock()


class DiscoveryGuard:
    """A discovery lock and the thread discovering under it; deep-copies and pickles as a new, idle one.

    The thread is not read from the lock: an interrupt in ``with`` entry or exit can leave the lock held by a thread that
    is no longer discovering, and locks can be disabled. Set and clear it inside the locked body.
    """

    __slots__ = ("_ident", "lock")

    def __init__(self) -> None:
        # Entered directly, not through a `__enter__` here: a Python wrapper would reopen the interrupt window that
        # CloneSafeLock closes by entering and exiting in C.
        self.lock = new_lock()
        self._ident: int | None = None

    def set_current(self) -> None:
        self._ident = get_ident()

    def clear(self) -> None:
        self._ident = None

    def is_current(self) -> bool:
        return self._ident == get_ident()

    def __reduce__(self) -> tuple[type["DiscoveryGuard"], tuple[()]]:
        return DiscoveryGuard, ()
