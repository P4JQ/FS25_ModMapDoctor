"""Load specialization / XML-block catalog and known vanilla vehicle type names."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_KNOWLEDGE_DIR = Path(__file__).resolve().parent
_SPEC_MAP_PATH = _KNOWLEDGE_DIR / "xml_block_to_specialization.json"

# Top-level vehicle XML children that are structural / store metadata,
# not specialization configuration roots.
STRUCTURAL_VEHICLE_TAGS: frozenset[str] = frozenset(
    {
        "storeData",
        "base",
        "components",
        "component",
        "i3dMappings",
        "i3dMapping",
        "configurations",
        "design",
        "designConfigurations",
        "configurationSets",
        "wearable",  # often present via base type; still mapped — keep out of skip if mapped
        "name",
        "function",
        "parentFile",
        "parentFileOverrides",
        "annotation",
        "public",
        "sounds",  # many vehicles use sounds without a dedicated Spec root name
    }
)

# Tags we never treat as specialization requirements even if docs mention them.
FORCE_SKIP_TAGS: frozenset[str] = frozenset(
    {
        "storeData",
        "base",
        "components",
        "component",
        "i3dMappings",
        "i3dMapping",
        "configurations",
        "configurationSets",
        "design",
        "designConfigurations",
        "parentFile",
        "parentFileOverrides",
        "annotation",
        "public",
        "l10n",
        "objectChange",
        "objectChanges",
    }
)

# Common vanilla type names from FS25 vehicleTypes.xml (name attribute).
# Used to distinguish "unknown typo" from "recognized base type".
# Specialization lists for these are not fully embedded; inheritance stops here.
KNOWN_VANILLA_VEHICLE_TYPES: frozenset[str] = frozenset(
    {
        "aiCombine",
        "aiTractor",
        "attachableCombine",
        "baseFillable",
        "car",
        "combine",
        "conveyorBelt",
        "cultivator",
        "cutter",
        "fertilizerSpreader",
        "fillableImplement",
        "forageHarvesterCutter",
        "forageWagon",
        "forwarder",
        "frontloader",
        "handTool",
        "harvester",
        "implement",
        "livestockTrailer",
        "loaderWagon",
        "locomotive",
        "manureBarrel",
        "manureSpreader",
        "mixerWagon",
        "mower",
        "pallet",
        "plow",
        "roller",
        "seedDrill",
        "seeder",
        "selfPropelledSprayer",
        "sowingMachine",
        "sprayer",
        "stonePicker",
        "stumpCutter",
        "Tedder",
        "tedder",
        "teleHandler",
        "tipper",
        "tractor",
        "trailer",
        "trainWagon",
        "transportTrailer",
        "treePlanter",
        "truck",
        "vehicle",
        "weeder",
        "windrower",
        "woodHarvester",
        "woodChipTrailer",
        "woodCrusherTrailer",
        "base",
        "baler",
        "baleLoader",
        "baleWrapper",
        "dischargeable",
        "dynamicMountAttacherTrailer",
        "hookLiftTrailer",
        "leveler",
        "skidSteer",
        "wheelLoader",
        "excavator",
        "shovel",
    }
)


@dataclass(frozen=True, slots=True)
class Fs25Catalog:
    """In-memory reference data for validators."""

    xml_block_to_specialization: dict[str, str]
    known_vehicle_specializations: frozenset[str]
    ambiguous_blocks: dict[str, tuple[str, ...]]
    known_vanilla_types: frozenset[str]
    force_skip_tags: frozenset[str]

    def specialization_for_block(self, tag: str) -> str | None:
        """Return required specialization name for a vehicle XML child tag."""
        if tag in self.force_skip_tags:
            return None
        return self.xml_block_to_specialization.get(tag)

    def ambiguous_specs_for_block(self, tag: str) -> tuple[str, ...] | None:
        specs = self.ambiguous_blocks.get(tag)
        return specs if specs else None

    def is_known_specialization(self, name: str) -> bool:
        lower_map = {s.lower(): s for s in self.known_vehicle_specializations}
        return name.lower() in lower_map

    def normalize_specialization(self, name: str) -> str:
        """Return canonical casing from docs when known, else original."""
        for spec in self.known_vehicle_specializations:
            if spec.lower() == name.lower():
                return spec
        return name

    def is_known_vanilla_type(self, type_name: str) -> bool:
        return type_name.lower() in {t.lower() for t in self.known_vanilla_types}


@lru_cache(maxsize=1)
def get_catalog() -> Fs25Catalog:
    raw = json.loads(_SPEC_MAP_PATH.read_text(encoding="utf-8"))
    mapping: dict[str, str] = dict(raw.get("xmlBlockToSpecialization", {}))
    # Never treat structural tags as specialization requirements.
    for tag in FORCE_SKIP_TAGS:
        mapping.pop(tag, None)

    ambiguous_raw = raw.get("ambiguousBlocks", {})
    ambiguous = {
        key: tuple(values)
        for key, values in ambiguous_raw.items()
        if key not in FORCE_SKIP_TAGS
    }

    specs = frozenset(raw.get("knownVehicleSpecializations", []))
    return Fs25Catalog(
        xml_block_to_specialization=mapping,
        known_vehicle_specializations=specs,
        ambiguous_blocks=ambiguous,
        known_vanilla_types=KNOWN_VANILLA_VEHICLE_TYPES,
        force_skip_tags=FORCE_SKIP_TAGS,
    )
