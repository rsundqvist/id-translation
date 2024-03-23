import pytest
from id_translation.transform import BitmaskTransformer


@pytest.mark.parametrize(
    "bitmask, expected",
    [
        (0b0000, []),
        (0b0001, []),
        (0b0010, []),  # Don't waste time decomposing powers of two
        (0b0011, [1, 2]),
        (0b0100, []),
        (0b0101, [1, 4]),
        (0b0110, [2, 4]),
        (0b0111, [1, 2, 4]),
        (0b1000, []),  # Don't waste time decomposing powers of two
        (0b1001, [1, 8]),
        (0b1010, [2, 8]),
        (0b1011, [1, 2, 8]),
        (0b1100, [4, 8]),
        (0b1101, [1, 4, 8]),
        (0b1110, [2, 4, 8]),
        (0b1111, [1, 2, 4, 8]),
    ],
)
def test_composite_bitmask(bitmask, expected):
    actual = BitmaskTransformer.decompose_bitmask(bitmask)
    assert actual == expected


def test_negative():
    for ni in range(-10, 0):
        assert BitmaskTransformer.decompose_bitmask(ni) == [], ni


def test_powers_of_two():
    for exponent in range(32):
        po2_bitmask = 2**exponent
        actual = BitmaskTransformer.decompose_bitmask(po2_bitmask)
        assert actual == [], f"{exponent=:>3} => bitmask={po2_bitmask:#034b}"
