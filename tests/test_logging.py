import logging

import pytest


def test_not_serializable_fails():
    with pytest.raises(TypeError):
        logging.root.info("This should fail!", extra=dict(bad_key={"sets aren't serializable"}))
