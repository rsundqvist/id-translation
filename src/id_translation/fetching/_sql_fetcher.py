import logging
import warnings
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Dict, Iterable, List, Literal, Optional, Set, TypeVar
from urllib.parse import quote_plus

import sqlalchemy
from rics.misc import tname
from rics.performance import format_perf_counter

from ..offline.types import PlaceholderTranslations
from ..types import ID, IdType
from . import exceptions, support
from ._abstract_fetcher import AbstractFetcher
from .exceptions import FetcherWarning
from .types import FetchInstruction


class SqlFetcher(AbstractFetcher[str, IdType]):
    """Fetch data from a SQL source. Requires SQLAlchemy.

    Args:
        connection_string: A SQLAlchemy connection string.
        password: Password to insert into the connection string. Will be escaped to allow for special characters. If
            given, the connection string must contain a password key, eg; ``dialect://user:{password}@host:port``.
        whitelist_tables: The only tables the ``SqlFetcher`` may access. Mutually exclusive with `blacklist_tables`.
        blacklist_tables: The only tables the ``SqlFetcher`` may not access. Mutually exclusive with `whitelist_tables`.
        schema: Database schema to use. Typically needed only if `schema` is not the default schema for the user
            specified in the connection string.
        include_views: If ``True``, the fetcher will discover and query views as well.
        fetch_all_limit: Maximum size of table to allow a fetch all-operation. 0=never allow. Ignore if ``None``.
        engine_kwargs: A dict of keyword arguments for :func:`sqlalchemy.create_engine`.
        **kwargs: Primarily passed to ``super().__init__``, then used as :meth:`selection_filter_type` kwargs.

    Raises:
        ValueError: If both `whitelist_tables` and `blacklist_tables` are given.

    Notes:
        Inheriting classes may override on or more of the following methods to further customize operation.

        * :meth:`create_engine`; initializes the SQLAlchemy engine. Calls ``create_engine``.
        * :meth:`parse_connection_string`; does basic URL encoding.
        * :meth:`make_table_summary`; creates :class:`TableSummary` instances. Calls ``get_approximate_table_size``.
        * :meth:`get_approximate_table_size`; default is ``SELECT count(*) FROM table``.
        * :meth:`selection_filter_type`; control what kind of filtering (if any) should be done when selecting IDs.
        * :meth:`finalize_statement`; adjust the final query, e.g. to apply additional filtering.

        Overriding should be done with care, as these may call each other internally.
    """

    def __init__(
        self,
        connection_string: str,
        password: str = None,
        whitelist_tables: Iterable[str] = None,
        blacklist_tables: Iterable[str] = (),
        schema: str = None,
        include_views: bool = False,
        fetch_all_limit: Optional[int] = 100_000,
        engine_kwargs: Dict[str, Any] = None,
        **kwargs: Any,
    ) -> None:
        if kwargs:
            import inspect

            parameters = set(inspect.signature(super().__init__).parameters)
            super_kwargs = {k: kwargs.pop(k) for k in parameters.intersection(kwargs)}
            self._select_params = kwargs
        else:  # pragma: no cover
            self._select_params = {}
            super_kwargs = {}
        super().__init__(**super_kwargs)

        self._engine = self.create_engine(connection_string, password, engine_kwargs or {})
        self._estr = str(self.engine)
        self._schema = schema
        self._reflect_views = include_views
        self._fetch_all_limit = fetch_all_limit

        self._blacklist = set(blacklist_tables)

        self._table_ts_dict: Optional[Dict[str, SqlFetcher.TableSummary]] = None

        if whitelist_tables is None:
            self._whitelist = set()
        else:
            if blacklist_tables:
                raise ValueError("At most one of whitelist and blacklist may be given.")  # pragma: no cover

            whitelist_tables = set(whitelist_tables)
            if len(whitelist_tables) == 0:
                self.close()
                msg = f"Got empty 'whitelist_tables' argument. No tables will be available to {self}."
                self.logger.getChild("sql").warning(msg)
                warnings.warn(msg, category=FetcherWarning, stacklevel=2)

            self._whitelist = set(whitelist_tables)

    @property
    def _summaries(self) -> Dict[str, "SqlFetcher.TableSummary"]:
        """Names and sizes of tables that the ``SqlFetcher`` may interact with."""
        if self._table_ts_dict is None:
            self._table_ts_dict = self._get_summaries()

        return self._table_ts_dict

    def fetch_translations(self, instr: FetchInstruction[str, IdType]) -> PlaceholderTranslations[str]:
        """Fetch columns from a SQL database."""
        ts = self._summaries[instr.source]
        columns = ts.select_columns(instr)
        select = sqlalchemy.select(*map(ts.columns.get, columns))  # type: ignore[arg-type]

        if instr.ids is None and not ts.fetch_all_permitted:  # pragma: no cover
            raise exceptions.ForbiddenOperationError(self._FETCH_ALL, f"disabled for table '{ts.name}'.")

        stmt = select if instr.ids is None else self._make_query(ts, select, set(instr.ids))
        stmt = self.finalize_statement(stmt, ts.id_column, ts.id_column.table)

        with self.engine.connect() as conn:
            records = tuple(map(tuple, conn.execute(stmt)))
        return PlaceholderTranslations(instr.source, tuple(columns), records)

    StatementType = TypeVar("StatementType", bound=sqlalchemy.sql.Executable)
    """Input and return bounds for :meth:`.finalize_statement`."""

    def finalize_statement(
        self,
        statement: StatementType,
        id_column: sqlalchemy.Column,  # type:ignore[type-arg]
        table: sqlalchemy.Table,
    ) -> StatementType:
        """Finalize a statement before execution. Does nothing by default.

        Args:
            statement: A pre-build select query.
            id_column: The ID column of `table`.
            table: Table from which the selection `select` is made.

        Returns:
            The final statement to execute.
        """
        return statement

    def _make_query(
        self,
        ts: "SqlFetcher.TableSummary",
        select: sqlalchemy.sql.Select,  # type: ignore[type-arg]
        ids: Set[IdType],
    ) -> sqlalchemy.sql.Select:  # type: ignore[type-arg]
        where = self.selection_filter_type(ids, ts, **self._select_params)

        if where == "in":
            return select.where(ts.id_column.in_(ids))
        if where == "between":
            return select.where(ts.id_column.between(min(ids), max(ids)))
        if where is None:
            return select

        raise ValueError(f"Bad response {where=} returned by {self.selection_filter_type=}.")  # pragma: no cover

    @property
    def online(self) -> bool:
        return self._engine is not None  # pragma: no cover

    @property
    def sources(self) -> List[str]:
        return list(self._summaries)

    @property
    def placeholders(self) -> Dict[str, List[str]]:
        return {name: list(ts.columns.keys()) for name, ts in self._summaries.items()}

    @property
    def allow_fetch_all(self) -> bool:
        return super().allow_fetch_all and all(s.fetch_all_permitted for s in self._summaries.values())

    def __str__(self) -> str:
        disconnected = "<disconnected>: " if not self.online else ""
        schema = f"[schema={self._schema!r}]" if self._schema else ""
        return f"{tname(self)}({disconnected}{self._estr}, tables{schema}={repr(self.sources or '<no tables>')})"

    @property
    def engine(self) -> sqlalchemy.engine.Engine:
        """Engine used by this fetcher.

        Returns:
            The ``Engine`` used for fetching.
        """
        self.assert_online()
        return self._engine

    def close(self) -> None:  # pragma: no cover
        if self._engine is None:
            return

        self.logger.getChild("sql").debug("Dispose %s", self._estr)
        self._table_ts_dict = {}
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
    def parse_connection_string(cls, connection_string: str, password: Optional[str]) -> str:  # pragma: no cover
        """Parse a connection string."""
        if password:
            if "{password}" in connection_string:
                connection_string = connection_string.format(password=quote_plus(password))
            else:  # pragma: no cover
                warnings.warn(
                    "A password was specified, but the connection string does not have a {password} key.", stacklevel=3
                )
        return connection_string

    def _get_summaries(self) -> Dict[str, "SqlFetcher.TableSummary"]:
        start = perf_counter()
        metadata = self.get_metadata()

        logger = self.logger.getChild("sql").getChild("discovery")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"{self._estr}: Metadata created in {format_perf_counter(start)}.")

        table_names = {t.name for t in metadata.tables.values()}
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

        ans = {}
        for name in tables:
            qualified_name = name if self._schema is None else f"{self._schema}.{name}"
            table = metadata.tables[qualified_name]
            id_column = self.id_column(table.name, (c.name for c in table.columns))
            if id_column in table.columns.keys():
                ans[str(name)] = self.make_table_summary(table, table.columns[id_column])
            else:
                whitelisted = table.name in self._whitelist
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
        """Create a table summary."""
        start = perf_counter()
        size = self.get_approximate_table_size(table, id_column)
        logger = self.logger.getChild("sql")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"{self._estr}: Counted {size} rows of table '{table.name}' in {format_perf_counter(start)}.")
        fetch_all_permitted = self._fetch_all_limit is None or size < self._fetch_all_limit
        return SqlFetcher.TableSummary(str(table.name), size, table.columns, fetch_all_permitted, id_column)

    def get_approximate_table_size(
        self,
        table: sqlalchemy.Table,
        id_column: sqlalchemy.Column,  # type: ignore[type-arg]
    ) -> int:
        """Return the approximate size of a table.

        Called only by the :meth:`make_table_summary` method during discovery. The default implementation performs a
        count on the ID column, which may be expensive.

        Args:
            table: A table object.
            id_column: The ID column in `table`.

        Returns:
            An approximate size for `table`.
        """
        stmt = sqlalchemy.func.count(id_column)
        stmt = self.finalize_statement(stmt, id_column, table)

        with self.engine.connect() as conn:
            return int(conn.execute(stmt).scalar())  # type: ignore[arg-type]

    def get_metadata(self) -> sqlalchemy.MetaData:
        """Create a populated metadata object."""
        metadata = sqlalchemy.MetaData(schema=self._schema)
        metadata.reflect(self.engine, only=tuple(self._whitelist) or None, views=self._reflect_views)
        return metadata

    @classmethod
    def selection_filter_type(
        cls,
        ids: Set[IdType],
        table_summary: "SqlFetcher.TableSummary",
        fetch_all_below: int = 25,
        fetch_all_above_ratio: float = 0.90,
        fetch_in_below: int = 1200,
        fetch_between_over: int = 10_000,
        fetch_between_max_overfetch_factor: float = 2.5,
    ) -> Literal["in", "between", None]:
        """Determine the type of filter (``WHERE``-query) to use, if any.

        In the descriptions below, ``len(table)`` refers to the :attr:`TableSummary.size`-attribute of `table_summary`.
        Bare select implies fetching the entire table.

        Args:
            ids: IDs to fetch.
            table_summary: A summary of the table that's about to be queried.
            fetch_all_below: Use bare select if ``len(ids) <= len(table)``.
            fetch_all_above_ratio: Use bare select if ``len(ids) > len(table) * ratio``.
            fetch_in_below: Always use ``IN``-clause when fetching less than `fetch_in_below` IDs.
            fetch_between_over: Always use ``BETWEEN``-clause when fetching more than `fetch_between_over` IDs.
            fetch_between_max_overfetch_factor: If number of IDs to fetch is between `fetch_in_below` and
                `fetch_between_over`, use this factor to choose between ``IN`` and ``BETWEEN`` clause.

        Returns:
            One of (``'in', 'between', None``), where ``None`` means bare select (fetch the whole table).

        Notes:
            Override this function to redefine ``SELECT`` filtering logic.
        """
        num_ids = len(ids)
        size = float("inf") if table_summary.size <= 0 else table_summary.size
        table = table_summary.name

        # Just fetch everything if we're getting "most of" the data anyway
        if size <= fetch_all_below or num_ids / size > fetch_all_above_ratio:
            if num_ids > size:  # pragma: no cover
                warnings.warn(f"Fetching {num_ids} unique IDs from {table=} which only has {size} rows.", stacklevel=2)
            return None

        if num_ids < fetch_in_below:
            return "in"

        min_id, max_id = min(ids), max(ids)

        if isinstance(next(iter(ids)), str) or num_ids > fetch_between_over:
            return "between"

        try:
            overfetch_factor = (max_id - min_id) / num_ids  # type: ignore
        except TypeError:  # pragma: no cover
            return "between"  # Non-numeric ID type

        if overfetch_factor > fetch_between_max_overfetch_factor:
            return "in"
        else:
            return "between"

    @dataclass(frozen=True)
    class TableSummary:
        """Brief description of a known table."""

        name: str
        """Name of the table."""
        size: int
        """Approximate size of the table."""
        columns: sqlalchemy.sql.ColumnCollection  # type: ignore[type-arg]
        """A flag indicating that the FETCH_ALL-operation is permitted for this table."""
        fetch_all_permitted: bool
        """A flag indicating that the FETCH_ALL-operation is permitted for this table."""
        id_column: sqlalchemy.Column  # type: ignore[type-arg]
        """The ID column of the table."""

        def select_columns(self, instr: FetchInstruction[str, IdType]) -> List[str]:
            """Return required and optional columns of the table."""
            return support.select_placeholders(instr, self.columns.keys())
