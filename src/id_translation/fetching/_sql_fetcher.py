import logging
import warnings
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Collection, Dict, Iterable, List, Literal, Optional, Set, Union
from urllib.parse import quote_plus
from uuid import UUID

import sqlalchemy
from packaging.version import Version
from rics.misc import format_kwargs, tname
from rics.performance import format_perf_counter
from sqlalchemy import BINARY, CHAR, TypeDecorator, __version__ as _sqla_version

from .. import _uuid_utils
from ..offline.types import PlaceholderTranslations
from ..types import ID, IdType
from . import exceptions
from ._abstract_fetcher import AbstractFetcher
from .exceptions import FetcherWarning
from .types import FetchInstruction


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
        * :meth:`select_where`; filter values on the `id_column` (from ``cast_id_column_to_uuid``) of the current table.
        * :meth:`make_table_summary`; creates :class:`TableSummary` instances.
        * :meth:`uuid_like`; determine if casting (with ``cast_id_column_to_uuid``) is needed.
        * :meth:`cast_id_column_to_uuid`; attempt to cast the `id_column` to ``UUID``.

        Overriding should be done with care, as methods may call each other internally.
    """

    _SQLALCHEMY_VERSION = Version(_sqla_version)

    def __init__(
        self,
        connection_string: str,
        password: str = None,
        whitelist_tables: Iterable[str] = None,
        blacklist_tables: Iterable[str] = (),
        schema: str = None,
        include_views: bool = False,
        engine_kwargs: Dict[str, Any] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        self._engine = self.create_engine(connection_string, password, engine_kwargs or {})
        self._estr = str(self.engine)
        self._schema = schema
        self._reflect_views = include_views

        self._blacklist = set(blacklist_tables)

        self._table_summaries: Dict[str, SqlFetcher.TableSummary] = {}

        self._whitelist: Optional[List[str]]
        if whitelist_tables is None:
            self._whitelist = None
        else:
            if blacklist_tables:
                raise ValueError("At most one of whitelist and blacklist may be given.")  # pragma: no cover
            self._whitelist = list(set(whitelist_tables))

            if len(self._whitelist) == 0:
                self.close()
                msg = f"Got empty 'whitelist_tables' argument. No tables will be available to {self}."
                self.logger.getChild("sql").warning(msg)
                warnings.warn(msg, category=FetcherWarning, stacklevel=2)

    @classmethod
    def select_where(
        cls,
        select: sqlalchemy.sql.Select,  # type: ignore[type-arg]
        *,
        ids: Optional[Set[IdType]],
        id_column: sqlalchemy.sql.ColumnElement,  # type: ignore[type-arg]
        table: sqlalchemy.Table,
    ) -> sqlalchemy.sql.Select:  # type: ignore[type-arg]
        """Add ``WHERE`` clause(s) to an ID select statement.

        .. warning::

           When overriding, keep in mind that returning the `select` statement as-is will perform an unfiltered select.

        Args:
            select: A ``sqlalchemy.sql.Select`` element. If returned as-is, all IDs in the table will be fetched.
            ids: Set of IDs to fetch. Will be ``None`` if :meth:`~AbstractFetcher.fetch_all` was called.
            id_column: The ID ``sqlalchemy.sql.Column`` of the `table`, from which `ids` are fetched.
            table: Table to `select` from.

        Returns:
            The final statement object to use.
        """
        if ids is None:
            return select

        if not ids:
            return select.where(sqlalchemy.false())

        if len(ids) == 1:
            return select.where(id_column == list(ids)[0])

        if len(ids) < 100:
            return select.where(id_column.in_(ids))

        min_id, max_id = min(ids), max(ids)
        try:
            if (max_id - min_id) / len(ids) < 2.5:  # type: ignore[operator]
                return select.where(id_column.between(min_id, max_id))
        except TypeError:
            pass  # str/UUID

        return select.where(id_column.in_(ids))

    def fetch_translations(self, instr: FetchInstruction[str, IdType]) -> PlaceholderTranslations[str]:
        ts = self._table_summaries[instr.source]

        if instr.fetch_all and not ts.fetch_all_permitted:  # pragma: no cover
            raise exceptions.ForbiddenOperationError(self._FETCH_ALL, f"disabled for table '{ts.name}'.")

        id_column: Union[sqlalchemy.sql.elements.Cast, sqlalchemy.Column]  # type: ignore[type-arg]
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

        select = self.select_where(select, ids=instr.ids, id_column=id_column, table=ts.id_column.table)

        logger = self.logger.getChild("select")
        if logger.isEnabledFor(logging.DEBUG):
            try:
                query = str(select.compile(self.engine, compile_kwargs={"literal_binds": True}))
                logger.debug(
                    f"Full SELECT query using engine: {self.engine}\n{query[:512] if len(query) > 512 else query}",
                    extra={"task_id": instr.task_id, "source": instr.source},
                )
            except Exception as e:
                logger.debug(f"Failed to render full SELECT query using engine: {self.engine}\n{select}", exc_info=e)

        with self.engine.connect() as conn:
            cursor = conn.execute(select)
            records = tuple(map(tuple, cursor))

        return PlaceholderTranslations(instr.source, tuple(cursor.keys()), records)

    def uuid_like(
        self,
        id_column: sqlalchemy.Column,  # type: ignore[type-arg]
        ids: Optional[Set[IdType]],
    ) -> Optional[bool]:
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
            is_uuid = isinstance(_uuid_utils.try_cast_one(first_id), UUID)
            if is_uuid:
                # Some dialect-specific types will evaluate to True, but only handle UUID-like strings and not actual
                # uuid.UUID-instances. This behavior has been corrected in SQLAlchemy > 2.
                return None if self._SQLALCHEMY_VERSION.major < 2 else True
            else:
                return False
        else:
            return None  # Decide solely based on column type.

    def _sqla_v1_uuid_hacks(
        self,
        id_column: sqlalchemy.Column,  # type: ignore[type-arg]
    ) -> Union[None, sqlalchemy.sql.elements.Cast, sqlalchemy.Column]:  # type: ignore[type-arg]
        length = getattr(id_column.type, "length", None)
        try:
            python_type = id_column.type.python_type
        except NotImplementedError:
            python_type = None

        if self.engine.dialect.name == "mssql" and "uniqueidentifier" == str(id_column.type).lower():
            # Microsoft db drivers (pymssql) handle this without help, but don't implement python_type (v1 only).
            return id_column

        if self.engine.dialect.name == "postgresql" and "uuid" == str(id_column.type).lower():
            # Postgres db drivers (pg8000/psycopg2) only work with string arguments before v2. We use uuid.UUID.
            return id_column.cast(_String32Uuid if length == 32 else _String36Uuid)

        if python_type is str:
            if length == 36:
                return id_column.cast(_String36Uuid)
            if length == 32:
                return id_column.cast(_String32Uuid)

        return None

    def cast_id_column_to_uuid(
        self,
        id_column: sqlalchemy.Column,  # type: ignore[type-arg]
        *,
        ids_are_uuid_like: Literal[True, "unknown"],
    ) -> Union[sqlalchemy.sql.elements.Cast, sqlalchemy.Column]:  # type: ignore[type-arg]
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
        if self._SQLALCHEMY_VERSION.major < 2:
            hacks = self._sqla_v1_uuid_hacks(id_column)
            if hacks is not None:
                return hacks

        python_type = id_column.type.python_type
        length = getattr(id_column.type, "length", None)

        if (ids_are_uuid_like is True or length == 32 or length == 36) and issubclass(python_type, str):
            if self.engine.dialect.name != "mysql":
                return id_column.cast(sqlalchemy.types.Uuid)

            # MySQL doesn't work even with SQLAlchemy > 2. This seems to be because UUIDs are converted to strings
            # without dashes by the driver (see log output), and databases contain dashed UUID-like strings.
            return id_column.cast(_String32Uuid if length == 32 else _String36Uuid)

        if length == 16 and issubclass(python_type, bytes):
            # Binary-form UUIDs, e.g. MySQL using UUID_TO_BIN and BIN_TO_UUID.
            return id_column.cast(_BinaryUuid)

        return id_column

    @property
    def online(self) -> bool:
        return self._engine is not None  # pragma: no cover

    def _initialize_sources(self, task_id: int) -> Dict[str, List[str]]:
        self._table_summaries = self._get_summaries(task_id)
        return {
            name: [str(c.name) for c in table_summary.columns] for name, table_summary in self._table_summaries.items()
        }

    @property
    def allow_fetch_all(self) -> bool:
        self.initialize_sources()  # Ensure self._table_summaries is populated.
        return super().allow_fetch_all and all(s.fetch_all_permitted for s in self._table_summaries.values())

    def __str__(self) -> str:
        disconnected = "<disconnected>: " if not self.online else ""

        kwargs = {"schema": self._schema, "blacklist": self._blacklist, "whitelist": self._whitelist}
        kwargs = {k: v for k, v in kwargs.items() if v}
        return f"{tname(self)}({disconnected}{self._estr}{', ' + format_kwargs(kwargs) if kwargs else ''})"

    @property
    def engine(self) -> sqlalchemy.engine.Engine:
        """The :class:`~sqlalchemy.engine.Engine` used by this fetcher."""
        self.assert_online()
        return self._engine

    def close(self) -> None:
        """Close the fetcher, discarding the :attr:`engine`."""
        if self._engine is None:
            return

        self.logger.getChild("sql").debug("Dispose %s", self._estr)
        self._table_summaries = {}
        self._engine.dispose()

    @classmethod
    def create_engine(
        cls,
        connection_string: str,
        password: Optional[str],
        engine_kwargs: Dict[str, Any],
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
    def parse_connection_string(cls, connection_string: str, password: Optional[str]) -> str:
        """Parse a connection string."""
        if password:
            if "{password}" in connection_string:
                connection_string = connection_string.format(password=quote_plus(password))
            else:
                warnings.warn(
                    "A password was specified, but the connection string does not have a {password} key.", stacklevel=3
                )
        return connection_string

    def _get_summaries(self, task_id: int) -> Dict[str, "SqlFetcher.TableSummary"]:
        start = perf_counter()
        metadata = self.get_metadata()

        logger = self.logger.getChild("sql").getChild("discovery")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"{self._estr}: Metadata created in {format_perf_counter(start)}.")

        table_names = {t.name for t in metadata.tables.values()}
        tables: Collection[str]
        if self._whitelist:
            tables = self._whitelist
        else:
            tables = table_names.difference(self._blacklist) if self._blacklist else table_names

        if not tables:  # pragma: no cover
            if self._whitelist:
                extra = f" (whitelist: {self._whitelist})"
            elif self._blacklist:
                extra = f" (blacklist: {self._blacklist})"
            else:
                extra = ""

            logger.warning(f"{self._estr}: No sources found{extra}. Available tables: {table_names}")
            return {}

        ans = {}
        for name in tables:
            qualified_name = name if self._schema is None else f"{self._schema}.{name}"
            table = metadata.tables[qualified_name]
            id_column = self.id_column(table.name, candidates=(c.name for c in table.columns), task_id=task_id)
            if id_column in table.columns.keys():
                ans[str(name)] = self.make_table_summary(table, table.columns[id_column])
            else:
                whitelisted = False if self._whitelist is None else table.name in self._whitelist
                unmapped = id_column is None

                if unmapped and not whitelisted:
                    self.logger.debug("Discarding table='%s'; no suitable ID column found.", qualified_name)
                    continue

                messages = []
                if whitelisted:
                    messages.append("Misconfigured whitelist table.")
                messages.append(
                    f"No suitable ID column found for the table {qualified_name!r}. "
                    f"Known columns: {sorted(c.name for c in table.columns)}."
                )
                if not unmapped:
                    messages.append(
                        f"This is likely caused by a bad override. "
                        f"Update or remove the override {ID!r} -> {id_column!r} from your mapping configuration."
                    )
                raise exceptions.UnknownPlaceholderError(" ".join(messages))

        return ans

    def make_table_summary(
        self,
        table: sqlalchemy.Table,
        id_column: sqlalchemy.Column,  # type: ignore[type-arg]
    ) -> "SqlFetcher.TableSummary":
        """Create a table summary.

        This function is called as a part of the fetcher initialization process.

        Args:
            table: The table (source) which is currently being processed.
            id_column: The ID column of `table`

        Returns:
            A summary object for `table`.
        """
        return self.TableSummary(
            name=str(table.name),
            columns=table.columns,
            fetch_all_permitted=True,
            id_column=id_column,
        )

    def get_metadata(self) -> sqlalchemy.MetaData:
        """Create a populated metadata object."""
        metadata = sqlalchemy.MetaData(schema=self._schema)
        metadata.reflect(self.engine, only=self._whitelist, views=self._reflect_views)
        return metadata

    @dataclass(frozen=True)
    class TableSummary:
        """Brief description of a known table."""

        name: str
        """Name of the table."""
        columns: sqlalchemy.sql.ColumnCollection  # type: ignore[type-arg]
        """A flag indicating that the FETCH_ALL-operation is permitted for this table."""
        fetch_all_permitted: bool
        """A flag indicating that the FETCH_ALL-operation is permitted for this table."""
        id_column: sqlalchemy.Column  # type: ignore[type-arg]
        """The ID column of the table."""


class _BinaryUuid(TypeDecorator):  # type: ignore[type-arg]
    impl = BINARY(16)
    cache_ok = True

    def process_bind_param(self, value: Optional[UUID], dialect: Any) -> Optional[bytes]:
        """Mimic UUID_TO_BIN."""
        return None if value is None else value.bytes

    def process_result_value(self, value: Optional[bytes], dialect: Any) -> Optional[UUID]:
        """Mimic BIN_TO_UUID."""
        return None if value is None else UUID(bytes=value)


class _String32Uuid(TypeDecorator):  # type: ignore[type-arg]
    impl = CHAR(32)
    cache_ok = True

    def process_bind_param(self, value: Optional[UUID], dialect: Any) -> Optional[str]:
        """To string representation without dashes."""
        return None if value is None else value.hex

    def process_result_value(self, value: Optional[str], dialect: Any) -> Optional[UUID]:
        """From string representation without dashes."""
        return None if value is None else UUID(value)


class _String36Uuid(TypeDecorator):  # type: ignore[type-arg]
    impl = CHAR(36)
    cache_ok = True

    def process_bind_param(self, value: Optional[UUID], dialect: Any) -> Optional[str]:
        """To string representation with dashes."""
        return None if value is None else str(value)

    def process_result_value(self, value: Optional[str], dialect: Any) -> Optional[UUID]:
        """From string representation with dashes."""
        return None if value is None else UUID(value)
