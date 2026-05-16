"""Simplified ORM models.

Downloaded from:
    https://id-translation.readthedocs.io/en/stable/documentation/examples/orm/orm.html

Used by the example script.
"""

from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    MappedAsDataclass,
    mapped_column,
    relationship,
)


class SakilaBase(DeclarativeBase, MappedAsDataclass):
    pass


class FilmActor(SakilaBase):
    __tablename__ = "film_actor"

    actor_id: Mapped[int] = mapped_column(ForeignKey("actor.actor_id"), primary_key=True)
    film_id: Mapped[int] = mapped_column(ForeignKey("film.film_id"), primary_key=True)


class Actor(SakilaBase):
    __tablename__ = "actor"

    actor_id: Mapped[int] = mapped_column(primary_key=True, init=False)
    first_name: Mapped[str] = mapped_column(String(45))
    last_name: Mapped[str] = mapped_column(String(45))

    films: Mapped[list["Film"]] = relationship(
        viewonly=True, secondary=FilmActor.__table__, repr=False
    )


class Staff(SakilaBase):
    __tablename__ = "staff"

    staff_id: Mapped[int] = mapped_column(primary_key=True, init=False)
    first_name: Mapped[str] = mapped_column(String(45))
    last_name: Mapped[str] = mapped_column(String(45))


class Customer(SakilaBase):
    __tablename__ = "customer"

    customer_id: Mapped[int] = mapped_column(primary_key=True, init=False)
    first_name: Mapped[str] = mapped_column(String(45))
    last_name: Mapped[str] = mapped_column(String(45))


class Film(SakilaBase):
    __tablename__ = "film"

    film_id: Mapped[int] = mapped_column(primary_key=True, init=False)
    title: Mapped[str] = mapped_column(String(255))
    release_year: Mapped[int | None] = mapped_column()


class Inventory(SakilaBase):
    __tablename__ = "inventory"

    inventory_id: Mapped[int] = mapped_column(primary_key=True, init=False)
    film_id: Mapped[int] = mapped_column(ForeignKey("film.film_id"))
    film: Mapped[Film] = relationship(viewonly=True)


class Rental(SakilaBase):
    __tablename__ = "rental"

    rental_id: Mapped[int] = mapped_column(primary_key=True, init=False)
    rental_date: Mapped[datetime] = mapped_column()
    inventory_id: Mapped[int] = mapped_column(ForeignKey("inventory.inventory_id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.customer_id"))
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.staff_id"))

    inventory: Mapped[Inventory] = relationship(viewonly=True)
    customer: Mapped[Customer] = relationship(viewonly=True)
    staff: Mapped[Staff] = relationship(viewonly=True)
