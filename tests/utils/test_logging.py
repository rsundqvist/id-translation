import logging

import pytest


def test_not_serializable_fails():
    logger = logging.getLogger(f"id_translation.{test_not_serializable_fails.__name__}")
    extra = dict(bad_key={"sets aren't serializable"})

    with pytest.raises(AssertionError, match=logger.name):
        logger.info("This should fail!", extra=extra)
