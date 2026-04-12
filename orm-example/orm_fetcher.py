from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Generic, Unpack

from sqlalchemy import Engine, inspect, select
from sqlalchemy.orm import ColumnProperty, DeclarativeBase, RelationshipProperty, Session
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.orm.strategy_options import joinedload
from sqlalchemy.sql.schema import Column
from sqlalchemy.sql.selectable import Select

from id_translation.fetching import AbstractFetcher
from id_translation.fetching.exceptions import UnknownPlaceholderError
from id_translation.fetching.types import FetchInstruction
from id_translation.offline.types import PlaceholdersTuple, PlaceholderTranslations
from id_translation.translator_typing import AbstractFetcherParams
from id_translation.types import ID, IdType


@dataclass
class _Info(Generic[IdType]):
    source: str
    placeholders: PlaceholdersTuple

    model: DeclarativeBase
    primary_key: InstrumentedAttribute[IdType]
    relationship_targets: dict[str, RelationshipProperty]


class OrmFetcher(AbstractFetcher[str, IdType]):
    """A simple fetcher that uses SqlAlchemy ORM models.

    Args:
        session: A session object.
        models: Models to expose as sources.
        **kwargs: See :class:`id_translation.fetching.AbstractFetcher`.
    """

    def __init__(
        self,
        engine: Engine,
        models: Iterable[DeclarativeBase],
        **kwargs: Unpack[AbstractFetcherParams[str, IdType]],
    ) -> None:
        engine.echo = True
        self._engine = engine
        self._models = [*models]

        self._infos: dict[str, _Info] = {}

        super().__init__(**kwargs)

    def _initialize(self, task_id: int) -> dict[str, _Info]:
        infos = {}

        for model in self._models:
            source = model.__name__
            placeholders = []
            relationship_targets = {}

            attr: RelationshipProperty[Any] | ColumnProperty[Any]
            for attr in inspect(model).attrs:
                placeholder = attr.key
                placeholders.append(placeholder)

                if isinstance(attr, RelationshipProperty):
                    relationship_targets[placeholder] = attr
                elif isinstance(attr, ColumnProperty):
                    expression = attr.expression
                    if isinstance(expression, Column):
                        print(f"id column candidate: {placeholder}: { expression.primary_key=}")
                    else:
                        raise NotImplementedError

            id_column = self.id_column(source, candidates=placeholders, task_id=task_id)
            if id_column is None:
                # We could've looked for primary_key=True here, but translaton won't work anyway if self.mapper isn't set up propely.
                raise RuntimeError(model)

            infos[source] = _Info(
                source=source,
                placeholders=tuple(placeholders),
                model=model,
                primary_key=getattr(model, id_column),
                relationship_targets=relationship_targets,
            )

        return infos

    def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:
        self._infos = self._initialize(task_id)
        return {info.source: [*info.placeholders] for info in self._infos.values()}

    def fetch_translations(self, instr: FetchInstruction[str, IdType]) -> PlaceholderTranslations[str]:
        select, placeholders = self._select(instr)

        session = Session(self._engine)
        # with session as session:
        records = tuple(
            tuple(getattr(orm_object, placeholder) for placeholder in placeholders)
            for orm_object in session.execute(select).scalars()
        )

        return PlaceholderTranslations(
            instr.source,
            placeholders=placeholders,
            records=records,
            id_pos=placeholders.index(ID),
        )

    def _select(self, instr: FetchInstruction[str, IdType]) -> tuple[Select[tuple[Any, ...]], PlaceholdersTuple]:
        info = self._infos[instr.source]

        if missing := instr.required.difference(info.placeholders):
            raise RuntimeError(f"{missing=}")  # Shouldn't happen

        stmt = select(info.model)

        for placeholder, target in info.relationship_targets.items():
            if placeholder in instr.placeholders:
                stmt = stmt.options(joinedload(target, innerjoin=True))

        if instr.ids is not None:
            stmt = stmt.where(info.primary_key.in_(instr.ids))

        return stmt, instr.placeholders
