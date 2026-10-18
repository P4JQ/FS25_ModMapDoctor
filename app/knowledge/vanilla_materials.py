"""Vanilla FS25 fill-type and fruit-type names used as a fallback catalog.

``data/maps/maps_fillTypes.xml`` is not in the documentation set, so this is
not a dump of that file. A name is included for one of two reasons:

* It is one of the core crop and ground materials shipped with this tool
  (wheat through sand).
* A vanilla script in ``Documentation/`` refers to it as ``FillType.NAME`` or
  ``FruitType.NAME``. ``UNKNOWN`` is excluded: it is the loader's empty value,
  not a material a mod should rely on.

Lookup is case-insensitive. Callers compare ``name.upper()`` against these sets.
"""

from __future__ import annotations

# Core crops and ground materials. Ground materials are fill types only.
_CORE_FILL_TYPES: frozenset[str] = frozenset(
    {
        "WHEAT",
        "BARLEY",
        "OATS",
        "CANOLA",
        "MAIZE",
        "SUNFLOWER",
        "SOYBEAN",
        "POTATO",
        "SUGARBEET",
        "COTTON",
        "SUGARCANE",
        "GRAPE",
        "OLIVE",
        "COFFEE",
        "RICE",
        "SPINACH",
        "STONE",
        "DIRT",
        "GRAVEL",
        "SAND",
    }
)

# Names that appear as FillType.NAME in Documentation/docs and
# Documentation/FS25-lua-scripting-main. UNKNOWN is intentionally absent.
_DOCUMENTED_FILL_TYPES: frozenset[str] = frozenset(
    {
        "AIR",
        "CHAFF",
        "DEF",
        "DIESEL",
        "DIGESTATE",
        "DRYGRASS_WINDROW",
        "ELECTRICCHARGE",
        "FERTILIZER",
        "FORAGE",
        "FORAGE_MIXING",
        "GRASS_WINDROW",
        "HERBICIDE",
        "LIME",
        "LIQUIDFERTILIZER",
        "LIQUIDMANURE",
        "LIQUIDSEEDTREATMENT",
        "MANURE",
        "METHANE",
        "POPLAR",
        "SEEDS",
        "SILAGE",
        "STONE",
        "STRAW",
        "TARP",
        "TREESAPLINGS",
        "WATER",
        "WHEAT",
        "WOOD",
        "WOODCHIPS",
    }
)

# Crops from the core list. Stone, dirt, gravel and sand are not fruits.
_CORE_FRUIT_TYPES: frozenset[str] = frozenset(
    name for name in _CORE_FILL_TYPES if name not in {"STONE", "DIRT", "GRAVEL", "SAND"}
)

# Names that appear as FruitType.NAME in the same documentation. UNKNOWN excluded.
_DOCUMENTED_FRUIT_TYPES: frozenset[str] = frozenset(
    {
        "CANOLA",
        "GRAPE",
        "GRASS",
        "MEADOW",
        "POPLAR",
        "WHEAT",
    }
)

VANILLA_FILL_TYPES: frozenset[str] = _CORE_FILL_TYPES | _DOCUMENTED_FILL_TYPES
VANILLA_FRUIT_TYPES: frozenset[str] = _CORE_FRUIT_TYPES | _DOCUMENTED_FRUIT_TYPES


def is_vanilla_fill_type(name: str | None) -> bool:
    """True when ``name`` is a base-game fill type (case-insensitive)."""
    return name is not None and name.upper() in VANILLA_FILL_TYPES


def is_vanilla_fruit_type(name: str | None) -> bool:
    """True when ``name`` is a base-game fruit type (case-insensitive)."""
    return name is not None and name.upper() in VANILLA_FRUIT_TYPES
