import logging
import warnings
from collections.abc import Collection, Iterable
from copy import deepcopy
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Generic, Literal, Self, TypeAlias, Unpack
from urllib.parse import quote_plus
from uuid import UUID

import sqlalchemy
from rics.misc import format_kwargs
from rics.strings import format_perf_counter as fmt_perf
from sqlalchemy import BINARY, CHAR, TypeDecorator

from .. import _uuid_utils
from .. import logging as _logging
from ..exceptions import ConnectionStatusError
from ..offline.types import PlaceholderTranslations
from ..translator_typing import AbstractFetcherParams
from ..types import ID, IdType
from . import exceptions
from ._abstract_fetcher import AbstractFetcher
from .exceptions import FetcherWarning
from .types import FetchInstruction

BETWEEN_CLAUSE_MIN_ID_COUNT = 100
BETWEEN_CLAUSE_MAX_OVERFETCH_FACTOR = 2.5


@dataclass(frozen=True)
class TableSummary(Generic[IdType]):
    """Brief description of a known table."""

    name: str
    """Name of the table."""
    columns: sqlalchemy.sql.ColumnCollection[str, Any]
    """A flag indicating that the FETCH_ALL-operation is permitted for this table."""
    fetch_all_permitted: bool
    """A flag indicating that the FETCH_ALL-operation is permitted for this table."""
    id_column: sqlalchemy.Column[IdType]
    """The ID column of the table."""


class SqlFetcher(AbstractFetcher[str, IdType]):
    """Fetch data from a SQL source.

    Args:
        connection_string: A SQLAlchemy connection string.
        password: Password to insert into the connection string. Will be escaped to allow for special characters. If
            given, the connection string must contain a password key, eg; ``dialect://user:{password}@host:port``.
        whitelist_tables: The only tables the fetcher may access.
        blacklist_tables: The only tables the fetcher may *not* access.
        schema: Database schema to use. Typically needed only if `schema` is not the default schema for the user
            specified in the connection string.
        include_views: If ``True``, the fetcher will discover and query views as well.
        engine_kwargs: A dict of keyword arguments for :func:`sqlalchemy.create_engine`.
        **kwargs: See :class:`AbstractFetcher`.

    Raises:
        ValueError: If both `whitelist_tables` and `blacklist_tables` are given.

    Notes:
        Inheriting classes may override on or more of the following methods to further customize operation.

        * :meth:`create_engine`; initializes the SQLAlchemy engine. Calls ``parse_connection_string``.
        * :meth:`parse_connection_string`; does basic URL encoding. Called by ``create_engine``.
        * :meth:`select_where`; filter values on the :attr:`~.TableSummary.id_column` of the current table.
        * :meth:`make_table_summary`; creates :class:`TableSummary` instances.
        * :meth:`uuid_like`; determine if :meth:`casting <cast_id_column_to_uuid>` is needed.
        * :meth:`cast_id_column_to_uuid`; attempt to cast the `id_column` to ``UUID``.

        Overriding should be done with care, as methods may call each other internally.
    """

    TableSummary: TypeAlias = TableSummary  # Reexport - part of API/docs.

    def __init__(
        self,
        connection_string: str,
        password: str | None = None,
        whitelist_tables: Iterable[str] | None = None,
        blacklist_tables: Iterable[str] = (),
        schema: str | None = None,
        include_views: bool = False,
        engine_kwargs: dict[str, Any] | None = None,
        **kwargs: Unpack[AbstractFetcherParams[str, IdType]],
    ) -> None:
        super().__init__(**kwargs)
        self._engine_kwargs = engine_kwargs or {}
        self._engine: sqlalchemy.Engine | None = None

        engine, engine_str = self._create_engine(connection_string, password)
        self._engine = engine
        self._estr = engine_str

        self._schema = schema
        self._reflect_views = include_views

        self._blacklist = set(blacklist_tables)

        self._table_summaries: dict[str, TableSummary[IdType]] = {}

        self._whitelist: list[str] | None
        if whitelist_tables is None:
            self._whitelist = None
        else:
            if blacklist_tables:
                raise ValueError("At most one of whitelist and blacklist may be given.")  # pragma: no cover
            self._whitelist = list(set(whitelist_tables))

            if len(self._whitelist) == 0:
                msg = f"Got empty 'whitelist_tables' argument. No tables will be available to {self}."
                self.logger.getChild("sql").warning(msg)
                warnings.warn(msg, category=FetcherWarning, stacklevel=2)

    def _create_engine(
        self,
        connection_string: str,
        password: str | None = None,
    ) -> tuple[sqlalchemy.Engine | None, str]:
        engine: sqlalchemy.Engine | None
        if not self.optional:
            engine = self.create_engine(connection_string, password, self._engine_kwargs)
            return engine, repr(str(engine.url))

        try:
            engine = self.create_engine(connection_string, password, self._engine_kwargs)
            engine_str = repr(str(engine.url))
        except Exception as e:
            engine = None
            engine_str = f"no engine: {e!r}"

        return engine, engine_str

    def select_where(
        self,
        select: sqlalchemy.sql.Select[tuple[IdType, ...]],
        *,
        ids: set[IdType] | None,  # noqa: ARG002
        id_column: sqlalchemy.sql.ColumnElement[IdType],  # noqa: ARG002
        table: sqlalchemy.Table,  # noqa: ARG002
    ) -> sqlalchemy.sql.Select[tuple[IdType, ...]]:
        """User method for modifying SELECT statements.

        The default implementation returns `select` as-is. Selection based on IDs is done before this method is called.
        Users may override this method to change what and which data is returned, e.g. by additional WHERE-clauses.

        Args:
            select: A ``sqlalchemy.sql.Select`` element. If returned as-is, all IDs in the table will be fetched.
            ids: Set of IDs to fetch. Will be ``None`` if :meth:`~AbstractFetcher.fetch_all` was called.
            id_column: The ID ``sqlalchemy.sql.Column`` of the `table`, from which `ids` are fetched.
            table: Table to `select` from.

        Returns:
            The final statement object to use.
        """
        return select

    @classmethod
    def _select_where(
        cls,
        select: sqlalchemy.sql.Select[tuple[IdType, ...]],
        *,
        ids: set[IdType] | None,
        id_column: sqlalchemy.sql.ColumnElement[IdType],
    ) -> sqlalchemy.sql.Select[tuple[IdType, ...]]:
        if ids is None:
            return select

        if not ids:
            return select.where(sqlalchemy.false())

        if len(ids) > BETWEEN_CLAUSE_MIN_ID_COUNT:
            min_id, max_id = min(ids), max(ids)
            try:
                if (max_id - min_id) / len(ids) < BETWEEN_CLAUSE_MAX_OVERFETCH_FACTOR:  # type: ignore[operator]
                    return select.where(id_column.between(min_id, max_id))
            except TypeError:
                pass  # str/UUID

        return select.where(id_column.in_(ids))

    def fetch_translations(self, instr: FetchInstruction[str, IdType]) -> PlaceholderTranslations[str]:
        ts = self._table_summaries[instr.source]

        if instr.fetch_all and not ts.fetch_all_permitted:  # pragma: no cover
            raise exceptions.ForbiddenOperationError("FETCH_ALL", f"disabled for table '{ts.name}'.")

        id_column: sqlalchemy.sql.elements.Cast | sqlalchemy.Column  # type: ignore[type-arg]
        ids_are_uuid_like = instr.enable_uuid_heuristics and self.uuid_like(ts.id_column, instr.ids)
        if ids_are_uuid_like is False:
            id_column = ts.id_column
        else:
            id_column = self.cast_id_column_to_uuid(
                ts.id_column,
                ids_are_uuid_like="unknown" if ids_are_uuid_like is None else True,
            )

        if instr.fetch_all and not self.selective_fetch_all:
            column_names = list(ts.columns.keys())
        else:
            column_names = [name for name in instr.placeholders if name in ts.columns]
        columns = [id_column if name == ts.id_column.name else ts.columns[name] for name in column_names]
        select = sqlalchemy.select(*columns)

        select = self._select_where(select, ids=instr.ids, id_column=id_column)
        select = self.select_where(select, ids=instr.ids, id_column=id_column, table=ts.id_column.table)

        self._log_query(select, logger_extra={"task_id": instr.task_id, "table": instr.source})

        with self.engine.connect() as conn:
            cursor = conn.execute(select)
            records = tuple(map(tuple, cursor))

        return PlaceholderTranslations(instr.source, tuple(cursor.keys()), records)

    def _log_query(
        self,
        select: sqlalchemy.sql.Select[tuple[IdType, ...]],
        logger_extra: dict[str, Any],
        query_length_limit: int = 512,
    ) -> None:
        if not (_logging.ENABLE_VERBOSE_LOGGING and self.logger.isEnabledFor(logging.DEBUG)):
            return

        try:
            query = str(select.compile(self.engine, compile_kwargs={"literal_binds": True}))
            if len(query) > query_length_limit:
                query = query[:query_length_limit]
            self.logger.debug(f"Full SELECT-query using {self.engine}:\n{query}", extra=logger_extra)
        except Exception as e:
            self.logger.debug(
                f"Failed to render full SELECT-query using {self.engine}:\n{select}",
                exc_info=e,
                extra=logger_extra,
            )

    def uuid_like(
        self,
        id_column: sqlalchemy.Column[IdType],
        ids: set[IdType] | None,
    ) -> bool | None:
        """Determine whether `id_column` should be passed to :meth:`cast_id_column_to_uuid`.

        .. note::

           * Will not be called unless :attr:`.Translator.enable_uuid_heuristics` is ``True``.
           * Only ``False`` will bypass calling :meth:`cast_id_column_to_uuid`.

        Return values:
           * ``True``: Attempt to cast using :meth:`cast_id_column_to_uuid` with ``ids_are_uuid_like=True``.
           * ``False``: Do not cast; :meth:`cast_id_column_to_uuid` will **not** be called.
           * ``None``: Attempt to cast using :meth:`cast_id_column_to_uuid` with ``ids_are_uuid_like='unknown'``.

        Args:
            id_column: The ID ``sqlalchemy.sql.Column`` of the table.
            ids: Set of IDs to fetch. Will be ``None`` if :meth:`~AbstractFetcher.fetch_all` was called.

        Returns:
            One of ``True``, ``False`` and ``None``. See above for explanation.
        """
        try:
            python_type = id_column.type.python_type
        except NotImplementedError:
            python_type = None

        if python_type is UUID:
            return True

        if ids:
            first_id = next(iter(ids))
            maybe_uuid = _uuid_utils.try_cast_one(first_id)
            is_uuid = isinstance(maybe_uuid, UUID)
            return is_uuid
        else:
            return None  # Decide solely based on column type.

    def cast_id_column_to_uuid(
        self,
        id_column: sqlalchemy.Column[IdType],
        *,
        ids_are_uuid_like: Literal[True, "unknown"],
    ) -> sqlalchemy.sql.elements.Cast[IdType] | sqlalchemy.Column[IdType]:
        """Apply UUID heuristics to the ID column.

        This function attempts cast the `id_column` to a suitable type by looking at the type of the column and the
        `ids_are_uuid_like`-flag.

        If the column is already UUID-like (as determined by :meth:`get_metadata`), the column is always returned as-is.

        Args:
            id_column: The ID ``sqlalchemy.sql.Column`` of the table.
            ids_are_uuid_like: One of ``True`` and ``'unknown'`` (never ``False``). The latter typically means that
                :meth:`~AbstractFetcher.fetch_all` was called, but could also be a normal "translation" call without IDs.

        Returns:
            The `id_column` with or without a cast applied.
        """
        python_type = id_column.type.python_type
        length = getattr(id_column.type, "length", None)

        uuid_string_lengths = {_String32Uuid.length, _String36Uuid.length}

        if (ids_are_uuid_like is True or length in uuid_string_lengths) and issubclass(python_type, str):
            if self.engine.dialect.name != "mysql":
                return id_column.cast(sqlalchemy.types.Uuid)  # type: ignore[arg-type]

            # MySQL doesn't work even with SQLAlchemy > 2. This seems to be because UUIDs are converted to strings
            # without dashes by the driver (see log output), and databases may contain dashed UUID-like strings.
            return id_column.cast(_String32Uuid if length == _String32Uuid.length else _String36Uuid)  # type: ignore[arg-type]

        if length == _BinaryUuid.length and issubclass(python_type, bytes):
            # Binary-form UUIDs, e.g. MySQL using UUID_TO_BIN and BIN_TO_UUID.
            return id_column.cast(_BinaryUuid)  # type: ignore[arg-type]

        return id_column

    @property
    def online(self) -> bool:
        return self._engine is not None  # pragma: no cover

    def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:
        if self._engine is None:
            raise ConnectionStatusError(f"disconnected: {self._estr}")

        self._table_summaries = self._get_summaries(task_id)
        return {
            table_name: [str(c.name) for c in table_summary.columns]  # table_name = source
            for table_name, table_summary in self._table_summaries.items()
        }

    @property
    def allow_fetch_all(self) -> bool:
        self.initialize_sources()  # Ensure self._table_summaries is populated.
        return super().allow_fetch_all and all(s.fetch_all_permitted for s in self._table_summaries.values())

    def __str__(self) -> str:
        disconnected = "<disconnected>: " if not self.online else ""

        kwargs: dict[str, Any] = {}
        if self._schema:
            kwargs["schema"] = self._schema
        if self._whitelist:
            kwargs["whitelist"] = self._whitelist
        elif self._table_summaries:
            kwargs["sources"] = [*self._table_summaries]

        pretty_kwargs = ", " + format_kwargs(kwargs, max_value_length=1024) if kwargs else ""
        return f"{type(self).__name__}({disconnected}{self._estr}{pretty_kwargs})"

    @property
    def engine(self) -> sqlalchemy.engine.Engine:
        """The :class:`~sqlalchemy.engine.Engine` used by this fetcher."""
        self.assert_online()
        assert self._engine is not None  # noqa: S101
        return self._engine

    def close(self) -> None:
        """Close the fetcher, discarding the :attr:`engine`."""
        if self._engine is None:
            return

        self.logger.debug("Dispose %s.", self._estr)
        self._table_summaries = {}
        self._engine.dispose()
        self._engine = None

    @classmethod
    def create_engine(
        cls,
        connection_string: str,
        password: str | None,
        engine_kwargs: dict[str, Any],
    ) -> sqlalchemy.engine.Engine:
        """Factory method used by ``__init__``.

        For a more detailed description of the arguments and the behaviour of this function, see the
        :class:`class docstring <SqlFetcher>`.

        Args:
            connection_string: A SQLAlchemy connection string.
            password: Password to insert into the connection string.
            engine_kwargs: A dict of keyword arguments for :func:`sqlalchemy.create_engine`.

        Returns:
            A new ``Engine``.
        """
        return sqlalchemy.create_engine(
            cls.parse_connection_string(connection_string, password),
            **engine_kwargs,
        )

    @classmethod
    def parse_connection_string(cls, connection_string: str, password: str | None) -> str:
        """Parse a connection string."""
        if password:
            if "{password}" in connection_string:
                connection_string = connection_string.format(password=quote_plus(password))
            else:
                warnings.warn(
                    "A password was specified, but the connection string does not have a {password} key.",
                    stacklevel=3,
                )
        return connection_string

    def _get_summaries(self, task_id: int) -> dict[str, TableSummary[IdType]]:
        start = perf_counter()
        metadata = self.get_metadata()

        logger = self.logger
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Metadata for {self._estr} created in {fmt_perf(start)}.")

        table_names = {t.name for t in metadata.tables.values()}
        tables: Collection[str]
        if self._whitelist:
            tables = self._whitelist
        else:
            tables = table_names.difference(self._blacklist) if self._blacklist else table_names

        if not tables:  # pragma: no cover
            extra = ""
            if self._whitelist:
                extra = f" (whitelist: {self._whitelist})"
            elif self._blacklist:
                extra = f" (blacklist: {self._blacklist})"

            logger.warning(f"{self._estr}: No sources found{extra}. Available tables: {table_names}")
            return {}

        discarded = []
        ans = {}
        for name in tables:
            qualified_name = name if self._schema is None else f"{self._schema}.{name}"
            table = metadata.tables[qualified_name]
            id_column_name = self.id_column(table.name, candidates=(c.name for c in table.columns), task_id=task_id)
            if id_column_name is None or (id_column := table.columns.get(id_column_name)) is None:
                reason = self._handle_unknown_table(id_column_name, table, qualified_name)
                if reason:
                    discarded.append((qualified_name, reason))
            else:
                ans[str(name)] = self.make_table_summary(table, id_column)

        if discarded and _logging.ENABLE_VERBOSE_LOGGING and self.logger.isEnabledFor(logging.DEBUG):
            per_reason: dict[str, list[str]] = {}
            for qualified_name, reason in discarded:
                per_reason.setdefault(reason, []).append(qualified_name)
            self.logger.debug(
                f"Discarded {len(discarded)} tables. Reason: {per_reason}",
                extra={"task_id": task_id, "reason": per_reason},
            )

        return ans

    def _handle_unknown_table(
        self,
        id_column: str | None,
        table: sqlalchemy.Table,
        table_name: str,
    ) -> str | None:
        whitelisted = False if self._whitelist is None else table.name in self._whitelist
        unmapped = id_column is None

        if unmapped and not whitelisted:
            return "no ID column"

        messages = []
        if whitelisted:
            messages.append("Misconfigured whitelist table.")
        messages.append(
            f"No suitable ID column found for the table {table_name!r}. "
            f"Known columns: {sorted(c.name for c in table.columns)}."
        )
        if not unmapped:
            messages.append(
                f"This is likely caused by a bad override. "
                f"Update or remove the override {ID!r} -> {id_column!r} from your mapping configuration."
            )
        raise exceptions.UnknownPlaceholderError(" ".join(messages))

    def make_table_summary(
        self,
        table: sqlalchemy.Table,
        id_column: sqlalchemy.Column[IdType],
    ) -> TableSummary[IdType]:
        """Create a table summary.

        This function is called as a part of the fetcher initialization process.

        Args:
            table: The table (source) which is currently being processed.
            id_column: The ID column of `table`

        Returns:
            A summary object for `table`.
        """
        return TableSummary(
            name=str(table.name),
            columns=table.columns.as_readonly(),
            fetch_all_permitted=True,
            id_column=id_column,
        )

    def get_metadata(self) -> sqlalchemy.MetaData:
        """Create a populated metadata object."""
        metadata = sqlalchemy.MetaData(schema=self._schema)
        metadata.reflect(self.engine, only=self._whitelist, views=self._reflect_views)
        return metadata

    def __deepcopy__(self, memo: dict[int, Any] = {}) -> Self:  # noqa: B006
        cls = self.__class__
        result = cls.__new__(cls)
        memo[id(self)] = result

        for k, v in self.__dict__.items():
            setattr(
                result,
                k,
                self._copy_engine(memo, v, self._engine_kwargs)
                if isinstance(v, sqlalchemy.Engine)
                else deepcopy(v, memo),
            )

        return result

    @staticmethod
    def _copy_engine(memo: dict[int, Any], engine: sqlalchemy.Engine, kwargs: dict[str, Any]) -> sqlalchemy.Engine:
        engine_id = id(engine)

        if engine_id in memo:
            return memo[engine_id]  # type: ignore[no-any-return]

        result = sqlalchemy.create_engine(engine.url, **kwargs)
        memo[engine_id] = result
        return result


SqlFetcher.TableSummary = TableSummary  # Reexport


class _BinaryUuid(TypeDecorator[UUID]):
    length: int = 16
    impl = BINARY(length)
    cache_ok = True

    def process_bind_param(self, value: UUID | None, _dialect: Any) -> bytes | None:
        """Mimic UUID_TO_BIN."""
        return None if value is None else value.bytes

    def process_result_value(self, value: bytes | None, _dialect: Any) -> UUID | None:
        """Mimic BIN_TO_UUID."""
        return None if value is None else UUID(bytes=value)


class _String32Uuid(TypeDecorator[UUID]):
    length: int = 32
    impl = CHAR(length)
    cache_ok = True

    def process_bind_param(self, value: UUID | None, _dialect: Any) -> str | None:
        """To string representation without dashes."""
        return None if value is None else value.hex

    def process_result_value(self, value: str | None, _dialect: Any) -> UUID | None:
        """From string representation without dashes."""
        return None if value is None else UUID(value)


class _String36Uuid(TypeDecorator[UUID]):
    length: int = 36
    impl = CHAR(length)
    cache_ok = True

    def process_bind_param(self, value: UUID | None, _dialect: Any) -> str | None:
        """To string representation with dashes."""
        return None if value is None else str(value)

    def process_result_value(self, value: str | None, _dialect: Any) -> UUID | None:
        """From string representation with dashes."""
        return None if value is None else UUID(value)
