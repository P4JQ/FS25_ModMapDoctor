"""Rule tables for the Lua auditor, derived from the vanilla FS25 sources.

Every rule carries its *evidence*: what the vanilla scripts
(Documentation/FS25-lua-scripting-main, Documentation/docs/script) show. The
auditor only flags something as outdated when the vanilla code either marks it
deprecated itself or never uses it while using a documented replacement. API
that vanilla code still uses (for example ``Utils.getNoNil`` or the raw
``getXMLString`` family in GUI code) is deliberately NOT flagged.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.models import Severity

_KNOWLEDGE_DIR = Path(__file__).resolve().parent
_DEPRECATED_XML_PATH = _KNOWLEDGE_DIR / "lua_deprecated_xml_paths.json"


@dataclass(frozen=True, slots=True)
class LegacyApiRule:
    """One outdated-API check applied to comment/string-free Lua code."""

    rule_id: str
    pattern: re.Pattern[str]
    summary: str
    replacement: str
    evidence: str
    severity: Severity = Severity.WARNING
    specializations_only: bool = False


def _rule(
    rule_id: str,
    pattern: str,
    summary: str,
    replacement: str,
    evidence: str,
    severity: Severity = Severity.WARNING,
    specializations_only: bool = False,
) -> LegacyApiRule:
    return LegacyApiRule(
        rule_id=rule_id,
        pattern=re.compile(pattern),
        summary=summary,
        replacement=replacement,
        evidence=evidence,
        severity=severity,
        specializations_only=specializations_only,
    )


LEGACY_API_RULES: tuple[LegacyApiRule, ...] = (
    _rule(
        "LUA-OLD-001",
        r"\bg_currentMission\s*\.\s*player\b(?!\w)",
        "g_currentMission.player is not used by FS25",
        "g_localPlayer (or g_currentMission.playerSystem for other players)",
        "0 uses in the vanilla sources; g_localPlayer is used 63 times in the "
        "vanilla scripts and 41 times in the specializations",
    ),
    _rule(
        "LUA-OLD-002",
        r"\bg_currentMission\s*\.\s*controlledVehicle\b",
        "g_currentMission.controlledVehicle is not used by FS25",
        "g_localPlayer:getCurrentVehicle()",
        "0 uses in the vanilla sources; getCurrentVehicle() is used 44 times",
    ),
    _rule(
        "LUA-OLD-003",
        r"\bg_currentMission\s*\.\s*vehicles\b",
        "g_currentMission.vehicles is not used by FS25",
        "g_currentMission.vehicleSystem.vehicles",
        "0 uses in the vanilla sources; vehicleSystem.vehicles is used by the "
        "vanilla VehicleSystem / VehicleDebug scripts",
    ),
    _rule(
        "LUA-OLD-004",
        r"\bg_currentMission\s*\.\s*isMultiplayer\b",
        "g_currentMission.isMultiplayer is not used by FS25",
        "g_currentMission.missionDynamicInfo.isMultiplayer",
        "0 uses in the vanilla sources; missionDynamicInfo.isMultiplayer is "
        "what VehicleSystem, FarmlandManager and the husbandry placeables read",
    ),
    _rule(
        "LUA-OLD-005",
        r"[:.]\s*getIsActiveForSound\s*\(",
        "Vehicle:getIsActiveForSound() is deprecated",
        "check getIsActive() / the sound conditions of the specialization instead",
        "Vehicle.lua prints 'Vehicle:getIsActiveForSound() is deprecated' when it is called",
    ),
    _rule(
        "LUA-OLD-006",
        r"[:.]\s*hasInputConflictWithSelection\s*\(",
        "Vehicle:hasInputConflictWithSelection() is deprecated",
        "remove the call (the vanilla implementation only logs a deprecation warning)",
        "Vehicle.lua logs 'Vehicle:hasInputConflictWithSelection() is deprecated!'",
    ),
    _rule(
        "LUA-OLD-007",
        r"\bBunkerSilo\s*\.\s*onCreate\b",
        "BunkerSilo.onCreate is deprecated",
        "register the bunker silo through the placeable / XML configuration",
        "BunkerSilo.onCreate calls Logging.error('BunkerSilo.onCreate is deprecated!')",
    ),
    _rule(
        "LUA-OLD-008",
        r"(?<![\w.:])get(?:XMLString|XMLInt|XMLFloat|XMLBool)\s*\(",
        "raw getXML*() call in a specialization",
        "xmlFile:getValue(key, default) via the XMLFile API",
        "vanilla specializations read XML through xmlFile:getValue about 3300 "
        "times and use raw getXML*() in only 2 places",
        severity=Severity.INFO,
        specializations_only=True,
    ),
)


@dataclass(frozen=True, slots=True)
class DeprecatedXmlPath:
    """A vehicle XML path that vanilla code reports as removed."""

    old: str
    new: str | None
    era: str | None


@lru_cache(maxsize=1)
def deprecated_xml_paths() -> dict[str, DeprecatedXmlPath]:
    """Map old absolute vehicle XML path -> replacement info."""
    try:
        rows = json.loads(_DEPRECATED_XML_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[LuaRules] Could not load {_DEPRECATED_XML_PATH.name}: {exc}")
        return {}
    return {
        row["old"]: DeprecatedXmlPath(row["old"], row.get("new"), row.get("era"))
        for row in rows
        if isinstance(row, dict) and row.get("old")
    }


# Pairs of vehicle-specialization event handlers that must be implemented
# together, otherwise the data written by one side cannot be read by the other.
STREAM_HANDLER_PAIRS: tuple[tuple[str, str], ...] = (
    ("onWriteStream", "onReadStream"),
    ("onWriteUpdateStream", "onReadUpdateStream"),
)

# Anything in an Event.run() that shows it knows about the network side.
NETWORK_SIDE_MARKERS: tuple[str, ...] = (
    "getIsServer",
    "getIsClient",
    "isServer",
    "isClient",
    "g_server",
    "g_client",
    "broadcastEvent",
    "sendEvent",
)
