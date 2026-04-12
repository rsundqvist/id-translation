from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql.schema import ForeignKey, UniqueConstraint
from sqlalchemy.sql.sqltypes import String


class Base(DeclarativeBase):
    pass


class Parent(Base):
    __tablename__ = "parent_table"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30))

    child: Mapped[Child] = relationship(back_populates="parent", lazy="raise_on_sql")


class Child(Base):
    __tablename__ = "child_table"
    __table_args__ = (UniqueConstraint("parent_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30))

    parent_id: Mapped[int] = mapped_column(ForeignKey("parent_table.id"))
    parent: Mapped[Parent] = relationship(back_populates="child")
