"""Integration for insertion and extraction of IDs and translations to and from various data structures."""

from ._data_structure_io import DataStructureIO
from ._resolve import register_io, resolve_io

__all__ = ["DataStructureIO", "resolve_io", "register_io"]
