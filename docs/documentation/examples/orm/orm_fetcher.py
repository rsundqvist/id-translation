"""A naive ORM fetching implementation.

Downloaded from:
    https://id-translation.readthedocs.io/en/stable/documentation/examples/orm/orm.html

Implementation of the ``MyOrmFetcher`` class.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Unpack

from sqlalchemy import Column, Engine, inspect, select
from sqlalchemy.orm import (
    DeclarativeBase,
    MapperProperty,
    RelationshipProperty,
    Session,
)
from sqlalchemy.orm.attributes import QueryableAttribute
from sqlalchemy.orm.strategy_options import joinedload
from sqlalchemy.sql.selectable import Select

from id_translation.fetching import AbstractFetcher
from id_translation.fetching.types import FetchInstruction
from id_translation.offline.types import (
    PlaceholderAttributes,
    PlaceholdersTuple,
    PlaceholderTranslations,
)
from id_translation.translator_typing import AbstractFetcherParams
from id_translation.types import IdType

ModelClass = type[DeclarativeBase]


@dataclass
class _OrmInfo(Generic[IdType]):
    source: str
    placeholders: PlaceholdersTuple

    model: ModelClass
    id_column: QueryableAttribute[IdType]
    relationships: dict[str, RelationshipProperty[Any]]


ModelsArg = Mapping[str, ModelClass] | Collection[ModelClass]
"""Valid source model input types."""


class MyOrmFetcher(AbstractFetcher[str, IdType]):
    """Sample fetcher implementation for SQLAlchemy ORM models.

    Uses ephemeral :class:`sqlalchemy.orm.Session` instances.

    Args:
        engine: SQLAlchemy engine instance.
        models: Models to expose as sources. Pass a mapping to specify source
            names. Pass a ``registry`` to infer.
        preload_attributes: Trigger lazy-loaded relations.
        **kwargs: See :class:`id_translation.fetching.AbstractFetcher`.
    """

    def __init__(
        self,
        engine: Engine,
        models: ModelsArg,
        *,
        preload_attributes: bool,
        **kwargs: Unpack[AbstractFetcherParams[str, IdType]],
    ) -> None:
        self._engine = engine
        self._models = _handle_models(models)

        self._infos: dict[str, _OrmInfo[IdType]] = {}

        self._preload_attributes = preload_attributes

        super().__init__(**kwargs)

    def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:
        self._infos = self._initialize(task_id)
        return {info.source: [*info.placeholders] for info in self._infos.values()}

    def fetch_translations(
        self, instr: FetchInstruction[str, IdType]
    ) -> PlaceholderTranslations[str]:
        stmt, placeholders = self._select(instr)

        with Session(self._engine) as session:
            records = tuple(
                self._to_record(obj, placeholders, instr.placeholder_attributes)
                for obj in session.execute(stmt).unique().scalars()
            )

        return PlaceholderTranslations(
            instr.source,
            placeholders=placeholders,
            records=records,
        )

    def _select(
        self, instr: FetchInstruction[str, IdType]
    ) -> tuple[Select[tuple[Any, ...]], PlaceholdersTuple]:
        info = self._infos[instr.source]

        if missing := instr.required.difference(info.placeholders):
            raise RuntimeError(f"{missing=}")  # Shouldn't happen. Bad override?

        stmt = select(info.model)

        joins = set(info.relationships).intersection(instr.placeholders)
        for attr in joins:
            stmt = stmt.options(joinedload(info.relationships[attr]))

        if instr.ids is not None:
            stmt = stmt.where(info.id_column.in_(instr.ids))

        return stmt, instr.placeholders

    def _to_record(
        self,
        orm_object: Any,
        placeholders: PlaceholdersTuple,
        placeholder_attributes: PlaceholderAttributes,
    ) -> tuple[Any, ...]:
        values = []
        for placeholder in placeholders:
            obj_attr = getattr(orm_object, placeholder)
            values.append(obj_attr)

            if self._preload_attributes:
                for path in placeholder_attributes.get(placeholder, ()):
                    self._traverse(obj_attr, path.split("."))

        return tuple(values)

    @classmethod
    def _traverse(cls, obj: Any, attr_path: list[str]) -> None:
        """Traverse attribute path, including indexing.

        .. note::

           The mini-language supports other primitives, e.g. None and float. For
           simplicity, we only cover the ``int`` case.

        .. warning::

           Does not handle chained indexing, e.g.  ``foo[0][1]`` will fail.

        Args:
            obj: An object to traverse.
            attr_path: Access path, e.g., ``["foo", "bar[123]", "baz"]``.
        """
        for attr in attr_path:
            key: int | str | None = None
            if attr[-1] == "]" and (idx := attr.find("[")) != -1:
                key = attr[idx + 1 : -1]  # E.g. "foo[123]" -> "123"
                if key.isdigit():
                    key = int(key)
                name = attr[:idx]
            else:
                name = attr

            if name:
                obj = getattr(obj, name)
            if key is not None:
                obj = obj[key]

    def _initialize(self, task_id: int) -> dict[str, _OrmInfo[IdType]]:
        infos = {}

        for source, model in self._models.items():
            placeholders = []
            relationships = {}

            attr: MapperProperty[Any]
            for attr in inspect(model).attrs:
                placeholders.append(attr.key)
                if isinstance(attr, RelationshipProperty):
                    relationships[attr.key] = getattr(model, attr.key)

            id_column = self._id_column(model, placeholders, source, task_id)
            if id_column is None:
                continue

            infos[source] = _OrmInfo(
                source=source,
                placeholders=tuple(placeholders),
                model=model,
                id_column=id_column,
                relationships=relationships,
            )

        return infos

    def _id_column(
        self,
        model: ModelClass,
        placeholders: list[str],
        source: str,
        task_id: int,
    ) -> QueryableAttribute[IdType] | None:
        id_column = self.id_column(source, candidates=placeholders, task_id=task_id)
        if id_column is not None:
            return getattr(model, id_column)

        s = suggest_id_column(model)
        self.logger.warning(f"Skip {source=}; no ID column. Suggestion: {s}")
        return None

    @classmethod
    def from_base_model(cls, base: ModelClass) -> dict[str, ModelClass]:
        mappers = base.registry.mappers
        if not mappers:
            raise ValueError("empty registry")

        rv = {}
        for mapper in mappers:
            model = mapper.entity
            if suggest_id_column(model) is not None:
                if model.__name__ in rv:
                    raise ValueError("duplicate model names")
                rv[model.__name__] = model
        return rv


def _handle_models(models: ModelsArg) -> dict[str, ModelClass]:
    if isinstance(models, Mapping):
        return dict(models)

    expected = len(models)
    rv = {model.__name__: model for model in models}
    if len(rv) != expected:
        raise ValueError("duplicate model names")
    return rv


def suggest_id_column(model: ModelClass) -> QueryableAttribute[Any] | None:
    """Attempt to derive a suitable ID column for `model`."""
    rv: None | QueryableAttribute[Any] = None

    for name in dir(model):
        attr = getattr(model, name)
        if (
            isinstance(attr, QueryableAttribute)
            and isinstance(attr.expression, Column)
            and attr.expression.primary_key
        ):
            if rv is None:
                rv = attr
            else:
                return None  # Ambiguous - multiple candidates found.

    return rv
