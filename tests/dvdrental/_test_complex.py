from dataclasses import dataclass

import pandas as pd
import pytest
import sqlalchemy

from .conftest import check_status, get_connection_string, get_translator

DIALECTS = [
    "mysql",
    "postgresql",
    "mssql",  # Quite slow, mostly since the (pyre-python) driver used doesn't support fast_executemany
]


@pytest.mark.parametrize("dialect", DIALECTS)
def test_complex_translation_format(dialect):
    check_status(dialect)
    engine = sqlalchemy.create_engine(get_connection_string(dialect))
    translator = get_translator(dialect)

    fmt = "{first_name} {last_name!r} from {address.address}, {address.district}[ joined in {create_date:%b %Y}.]"
    customers = [130, 459, 408, 333, 222]
    expected = _get_expected(fmt, customers, "customer", engine)

    actual = translator.copy(fmt=fmt).translate(customers, names="customer_id")
    assert actual == expected


def _get_expected(fmt, ids, table, engine):
    query = """
    SELECT
        customer_id,
        create_date,
        first_name,
        last_name,
        a.address AS "address.address",
        a.district AS "address.district"
    FROM {table}
             LEFT JOIN address a on {table}.address_id = a.address_id
    WHERE {table}_id = {id}
    """

    @dataclass
    class Address:
        address: str
        district: str

    def func(sid):
        kwargs = pd.read_sql(query.format(table=table, id=sid), engine, parse_dates="create_date").iloc[0].to_dict()
        kwargs["address"] = Address(kwargs.pop("address.address"), district=kwargs.pop("address.district"))
        return fmt.format(**kwargs)

    expected = list(map(func, ids))
    return expected
