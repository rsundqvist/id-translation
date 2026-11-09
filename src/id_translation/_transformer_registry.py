from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from copy import deepcopy
from functools import partial
from threading import RLock
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Generic, Self

from rics.types import LiteralHelper

from ._utils.emit_warning import emit_warning
from .exceptions import TransformerConflictError, TransformerStateError
from .fetching import AbstractFetcher, Fetcher, MultiFetcher
from .transform import TransformerStack, as_transformer
from .transform._impl.stack import _chain
from .transform.types import OnExistingTransformer, Transformer, Transformers
from .types import IdType, NameType, SourceType

if TYPE_CHECKING:
    from ._translator import Translator

ON_EXISTING_HELPER: LiteralHelper[OnExistingTransformer] = LiteralHelper(
    OnExistingTransformer,
    default_name="on_existing",
    type_name="OnExistingTransformer",
)


class TransformerRegistry(Generic[NameType, SourceType, IdType]):
    """The transformers of one ``Translator``, and the lifecycle that settles them.

    Registrations arrive from the constructor (including the main file's ``[transform]``), and from the fetcher:
    :meth:`~id_translation.fetching.Fetcher.get_transformer` first, then its ``[fetching.transform]``-section. Both
    come from the fetcher that serves the source, so a discarded or outranked fetcher's transformers never apply. The
    fetcher is asked once per data source, so a copy that carries the answer over must not ask again, and one given an
    explicit set must not ask at all. The set settles at the first ``Translator.initialize_sources()`` call not given
    ``settle_transformers=False``, explicit or implicit, and is read-only from then on; an offline instance settles at
    construction. Settling only after the fetcher has been asked is what keeps its answer from being locked out.

    Methods that read the ``Translator`` take it as `owner` rather than store it. The instance holds its registry, so
    a back-reference would make each one a cycle, kept alive with its fetcher until the cyclic garbage collector runs.
    """

    def __init__(self) -> None:
        self._transformers: Transformers[SourceType, IdType] = {}
        # Whether the `Fetcher.get_transformer` pass has run; see `apply_from_fetcher`. Nothing is cached from it, so a
        # pass that raised simply runs again.
        self.queried: bool = False
        self._frozen: bool = False
        # Whether the owner has run source discovery. Its own flag: a copy given explicit transformers is `queried`
        # without its fetcher having discovered anything.
        self.discovered: bool = False
        # Serializes first use: discovery, the fetcher pass and settling, and a copy's snapshot of them. Checked twice,
        # so a settled registry never takes it.
        # Reentrant, since an overridden `register_transformer` may call back into the Translator.
        self.lock = RLock()

    def __getstate__(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if k != "lock"}

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)
        self.lock = RLock()

    @property
    def frozen(self) -> bool:
        return self._frozen

    @property
    def transformers(self) -> Mapping[SourceType, Transformer[IdType]]:
        """Read-only view of the settled transformers, one per source.

        Raises:
            TransformerStateError: If the registry is not frozen. Inspecting must not settle the set as a side
                effect, so callers that want a view before first use must `freeze` deliberately.
        """
        if not self._frozen:
            raise TransformerStateError(
                "Transformers are not settled until first use.",
                hints="Call Translator.initialize_sources() to settle them now, or read them after translating.",
            )

        return MappingProxyType(self._transformers)

    def settled(self, owner: "Translator[NameType, SourceType, IdType]") -> Mapping[SourceType, Transformer[IdType]]:
        if not self._frozen:
            with self.lock:
                if not self._frozen:
                    self.freeze(owner)

        return MappingProxyType(self._transformers)

    def freeze(
        self,
        owner: "Translator[NameType, SourceType, IdType]",
        sources: Iterable[SourceType] | None = None,
        *,
        report: bool = True,
    ) -> None:
        """Settle the transformers, dropping any that name a source outside `sources`.

        Nothing is dropped when there are no sources to keep and the owner serves unlisted ones. Idempotent, and
        narrowing only: a second call may trim further but never reopens the set.

        Args:
            owner: The instance these belong to.
            sources: Sources to keep. Defaults to the owner's.
            report: Whether to warn about what was dropped. Pass ``False`` when the caller chose `sources` and so
                already knows, as :meth:`~id_translation.Translator.go_offline` does for a subset snapshot.
        """
        keep = list(owner.sources if sources is None else sources)

        if keep or not owner._serves_unlisted_sources():
            known = set(keep)
            if dropped := [s for s in self._transformers if s not in known]:
                # Report before dropping: promoted to an error, this must leave the misconfiguration in place, or it
                # vanishes from the retry and the instance settles as if nothing was wrong.
                if report:
                    msg = f"Dropped transformers for sources that are not served: {dropped}.\nHint: Served: {keep}."
                    if unresolved := self._unresolved_children(owner):
                        msg += (
                            f"\nNote: source discovery raised for {len(unresolved)} optional fetcher(s), so what they"
                            f" would have served is unknown: {unresolved}."
                        )
                    emit_warning(msg)

                # Rebound, not trimmed in place: a view handed out before `go_offline` narrows the set must not change.
                self._transformers = {s: t for s, t in self._transformers.items() if s in known}

        self._frozen = True

    def register(
        self,
        source: SourceType,
        transformer: Transformer[IdType] | Sequence[Transformer[IdType]],
        on_existing: OnExistingTransformer,
    ) -> None:
        if self._frozen:
            # One hint for every way of settling. A copy replaces the whole set, so the hint shows how to keep it.
            raise TransformerStateError(
                f"Cannot register for {source!r}: the transformers are settled.",
                source=source,
                hints=(
                    "Register before the transformers settle, or copy with the full set: "
                    f"translator.copy(transformers={{**translator.transformers, {source!r}: ...}})."
                ),
            )

        on_existing = ON_EXISTING_HELPER.check(on_existing)
        new = as_transformer(transformer)

        registered = self._transformers.get(source)
        if registered is not None:
            if on_existing == "append":
                new = TransformerStack(registered, new)  # May warn about a duplicate before anything is committed.
            elif on_existing == "raise":
                raise TransformerConflictError(
                    f"Transformer {registered!r} is already registered for {source!r}.",
                    hints="Pass on_existing='append' to chain onto it, or 'overwrite' to replace it.",
                )

        self._transformers[source] = new

    def apply_from_fetcher(self, owner: "Translator[NameType, SourceType, IdType]") -> None:
        """Ask the fetcher what it provides and has configured, and register it ahead of what is already registered."""
        if not self.queried:
            # Derived fresh from current truth each call; a failed pass mutates nothing, so the next simply asks again.
            # No cached answer exists to go stale. Warn first: promoted to an error, the retry must warn again.
            self._report_unserved_configured(owner)
            self._register_from_fetcher(owner, self._collect_provided(owner))
            self.queried = True

    @staticmethod
    def _report_unserved_configured(owner: "Translator[NameType, SourceType, IdType]") -> None:
        """Warn about ``[fetching.transform]``-sections for sources their own fetcher never discovered.

        A source the fetcher discovered but lost to a higher-ranked one is not reported: ignoring source conflicts
        includes the transformers a fetcher brings along. Neither is a fetcher discarded as optional.
        """

        def leaves(fetcher: Fetcher[SourceType, IdType]) -> Iterator[Fetcher[SourceType, IdType]]:
            if isinstance(fetcher, MultiFetcher):
                for child in fetcher.children:
                    yield from leaves(child)
            else:
                yield fetcher

        if owner._fetcher is None:
            return  # Offline: there is no fetcher, and so no fetcher's sections.

        for leaf in leaves(owner._fetcher):
            if not isinstance(leaf, AbstractFetcher) or not leaf._transform_config:
                continue
            discovered = set(leaf.sources)
            if unknown := [s for s in leaf._transform_config if s not in discovered]:
                where = f"'{leaf.config_file}'" if leaf.config_file else leaf
                emit_warning(
                    f"Dropped [fetching.transform]-sections in {where} for sources its fetcher never discovered:"
                    f" {unknown}.\nHint: Discovered: {sorted(map(str, discovered))}."
                )

    @staticmethod
    def _collect_provided(owner: "Translator[NameType, SourceType, IdType]") -> Transformers[SourceType, IdType]:
        """Query every source, applying nothing: a raising fetcher must leave the instance untouched."""
        provided: Transformers[SourceType, IdType] = {}

        for source in owner.sources:
            try:
                transformer = owner.fetcher.get_transformer(source)
                chain = [] if transformer is None else [as_transformer(transformer)]  # A bad answer raises here.
            except Exception as e:
                e.add_note(f" - Raised by Fetcher.get_transformer({source!r}) on fetcher={owner.fetcher}.")
                raise

            chain.extend(owner.fetcher._configured_transformers(source))
            if chain:
                provided[source] = _chain(chain, where=partial(_where, owner.fetcher, source))

        return provided

    @contextmanager
    def _atomic(self, note: str | None = None) -> Iterator[None]:
        backup = self._transformers.copy()
        try:
            yield
        except BaseException as e:  # KeyboardInterrupt too: a half-registered set would chain twice on the retry.
            self._transformers.clear()
            self._transformers.update(backup)
            if note is not None:
                e.add_note(note)
            raise

    def _register_from_fetcher(
        self,
        owner: "Translator[NameType, SourceType, IdType]",
        transformers: Transformers[SourceType, IdType],
    ) -> None:
        with self._atomic(f" - Raised while registering a transformer provided by fetcher={owner.fetcher}."):
            for source, provided in transformers.items():
                registered = self._transformers.get(source)
                # No dedup: declaring what the fetcher already provides is the redundancy this library exists to remove,
                # so it chains like any other pair and `TransformerStack` reports the repeat.
                if registered is None:
                    chain = provided
                else:
                    where = partial(_where, owner.fetcher, source, registered=True)
                    chain = _chain([provided, registered], where=where)
                # The public method, so that an override sees what the fetcher contributed.
                owner.register_transformer(source, chain, on_existing="overwrite")

    @staticmethod
    def _unresolved_children(owner: "Translator[NameType, SourceType, IdType]") -> list[str]:
        fetcher = owner._fetcher
        return fetcher._unresolved_children() if isinstance(fetcher, MultiFetcher) else []

    def inherit(self, *, discovered: bool, complete: bool) -> None:
        """Set the state of a copy given its own set, rather than the original's.

        Discovery carries over: the copy's fetcher, shared or cloned, has discovered what the original's had. If
        `complete` (the set is not ``None``), the fetcher is never asked for transformers; otherwise it is asked on
        first use, as the constructor does.
        """
        self.discovered = discovered
        self.queried = complete

    def copy(self, owner: "Translator[NameType, SourceType, IdType]") -> Self:
        cls = type(self)
        new = cls()
        new.discovered = self.discovered
        new.queried = self.queried
        new._frozen = self._frozen
        try:
            new._transformers = deepcopy(self._transformers)
            return new
        except TypeError:
            pass  # Retry per source below, to attribute the failure and reuse only what cannot be cloned.

        # One memo keeps members that transformers share shared in the copy. A failed attempt's entries are rolled
        # back, so a later clone never adopts its half-built shell or the original in place of a copy.
        memo: dict[int, Any] = {}
        clones: dict[int, Transformer[IdType]] = {}

        for source, transformer in self._transformers.items():
            if (clone := clones.get(id(transformer))) is None:
                mark = len(memo)  # `deepcopy` only ever inserts into the memo, and dicts preserve insertion order.
                try:
                    clone = deepcopy(transformer, memo)
                except TypeError as e:
                    for key in list(memo)[mark:]:
                        del memo[key]
                    owner_name = type(owner).__name__
                    emit_warning(
                        f"Failed to clone the transformer for {source!r} (TypeError: {e})."
                        " Caller instance will be reused."
                        f"\nHint: Pass the set you want to {owner_name}.copy(transformers=...), which also stops the"
                        " copy asking the fetcher for more.",
                    )
                    clone = transformer

                clones[id(transformer)] = clone

            new._transformers[source] = clone

        return new


def _where(fetcher: Fetcher[SourceType, IdType], source: SourceType, *, registered: bool = False) -> str:
    """Name the source and the fetcher serving it in a duplicate warning: a member's repr may not say which to fix."""
    top, parent = fetcher, None
    while isinstance(fetcher, MultiFetcher):  # The serving leaf, not a dump of every child.
        parent, fetcher = fetcher, fetcher.get_child(source)

    if parent is not None and parent is top:
        serving = parent.format_child(fetcher)  # Rank, hex ID and file. A nested rank would be the wrong one.
    elif isinstance(fetcher, AbstractFetcher) and fetcher.config_file:
        serving = f"fetcher={fetcher} (file='{fetcher.config_file}')"
    else:
        serving = f"fetcher={fetcher}"

    if registered:
        return (
            f"for source={source!r}, provided by {serving} and registered on the Translator (e.g. from a top-level"
            " [transform] section)"
        )
    return f"for source={source!r} from {serving}"
