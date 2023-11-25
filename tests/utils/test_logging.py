import logging

import pytest


def test_not_serializable_fails():
    logger = logging.getLogger("the-logger")
    extra = dict(bad_key={"sets aren't serializable"})

    with pytest.raises(AssertionError, match="the-logger"):
        logger.info("This should fail!", extra=extra)
