from dataclasses import dataclass
from os import getenv
from sys import platform

import pytest
import sqlalchemy

from id_translation import Translator

from .conftest import DIALECTS, check_status, get_connection_string, setup_for_dialect

pytestmark = [
    pytest.mark.xfail(reason="Not implemented", strict=True),
    pytest.mark.skipif(
        getenv("CI") == "true" and platform != "linux",
        reason="No Docker for Mac and Windows in CI/CD.",
    ),
]


@pytest.mark.parametrize("dialect", DIALECTS)
def test_complex_translation_format(dialect):
    check_status(dialect)
    engine = sqlalchemy.create_engine(get_connection_string(dialect))
    translator: Translator[str, str, int] = Translator.from_config(*setup_for_dialect(dialect))

    fmt = "{first_name} {last_name!r} from {address.address}, {address.district}[ joined in {create_date:%b %Y}.]"
    customers = [130, 459, 408, 333, 222]
    expected = _get_expected(fmt, customers, "customer", engine)

    actual = translator.translate(customers, names="customer_id", fmt=fmt)
    assert actual == expected


def _get_expected(fmt, ids, table, engine):
    query = f"""
    SELECT
        customer_id,
        create_date,
        first_name,
        last_name,
        a.address AS "address.address",
        a.district AS "address.district"
    FROM {table}
             LEFT JOIN address a on {table}.address_id = a.address_id
    WHERE {table}_id = {{id}}
    """

    @dataclass(frozen=True)
    class Address:
        address: str
        district: str

    def func(sid):
        with engine.connect() as conn:
            cursor_result = conn.execute(sqlalchemy.text(query.format(id=sid)))
            kwargs = {key: value for key, value in zip(cursor_result.keys(), cursor_result.fetchone())}

        kwargs["address"] = Address(kwargs.pop("address.address"), district=kwargs.pop("address.district"))
        return fmt.format(**kwargs)

    return list(map(func, ids))
