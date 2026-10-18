"""Static knowledge derived from FS25 / GE10 documentation."""

from app.knowledge.fs25_catalog import Fs25Catalog, get_catalog
from app.knowledge.vanilla_materials import (
    VANILLA_FILL_TYPES,
    VANILLA_FRUIT_TYPES,
    is_vanilla_fill_type,
    is_vanilla_fruit_type,
)

__all__ = [
    "Fs25Catalog",
    "VANILLA_FILL_TYPES",
    "VANILLA_FRUIT_TYPES",
    "get_catalog",
    "is_vanilla_fill_type",
    "is_vanilla_fruit_type",
]
