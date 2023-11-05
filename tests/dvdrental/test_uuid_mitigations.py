from os import getenv
from sys import platform
from typing import Callable
from uuid import UUID

import pandas as pd
import pytest

from id_translation import Translator
from id_translation.fetching import SqlFetcher
from id_translation.mapping import Mapper
from id_translation.types import IdType

from .conftest import DIALECTS, get_connection_string

xfail_sqlalchemy_v1 = pytest.mark.xfail(
    SqlFetcher._SQLALCHEMY_VERSION.major < 2,
    reason="Needs SQLAlchemy version 2",
    strict=True,
)

pytestmark = [
    pytest.mark.skipif(
        getenv("CI") == "true" and platform != "linux",
        reason="No Docker for Mac and Windows in CI/CD.",
    ),
    pytest.mark.filterwarnings("ignore"),
]


EXPECTED = {
    "3F333DF6-90a4-4fda-8dd3-9485d27cee36": "mixed",
    "6ecd8c99-4036-403d-bf84-cf8400f67836": "lower",
    "40E6215D-B5C6-4896-987C-F30F3678F608": "upper",
}

_TESTED_DIALECTS = set()


def run(dialect: str, *, use_uuid_column: bool, id_type: Callable[[str], IdType]) -> None:
    table = "uuid_test_table"

    fetcher: SqlFetcher[IdType] = SqlFetcher(
        get_connection_string(dialect),
        mapper=Mapper(overrides={"id": "uuid" if use_uuid_column else "str_uuid"}),
        whitelist_tables=[table],
        selective_fetch_all=False,
    )

    translator: Translator[str, str, IdType] = Translator(fetcher, fmt="{comment}", enable_uuid_heuristics=True)
    translatable = pd.Series({uuid: id_type(uuid) for uuid in EXPECTED})

    actual = translator.translate(translatable, names=table).to_dict()
    assert actual == EXPECTED
    assert translator.online

    # This should be done after, or we might "cheat" on the selection step. Once fetched, IDs fetched will be coerced to
    # uuid.UUID by the MagicDict. This may mask issues in online-mode related to the generated WHERE-clause.
    translator.store()
    assert not translator.online
    assert sorted(translator.cache[table]) == sorted(UUID(e) for e in EXPECTED)


@pytest.mark.parametrize("id_type", [str, UUID])
class Base:
    dialect: str

    @classmethod
    def setup_class(cls):
        _TESTED_DIALECTS.add(cls.dialect)

    def test_uuid_column(self, id_type):
        run(self.dialect, use_uuid_column=True, id_type=id_type)

    def test_string_column(self, id_type):
        run(self.dialect, use_uuid_column=False, id_type=id_type)


class TestMySQL(Base):
    dialect = "mysql"


class TestPostgres(Base):
    dialect = "postgresql"

    @xfail_sqlalchemy_v1
    def test_string_column(self, id_type):
        super().test_string_column(id_type)


class TestMicrosoft(Base):
    dialect = "mssql"


def teardown_module(module):
    assert _TESTED_DIALECTS == set(DIALECTS)
