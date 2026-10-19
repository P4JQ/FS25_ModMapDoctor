"""Static checks for placeable.husbandry XML the FS25 loader rejects or skips.

Every rule below is an attribute test copied from an onLoad body in
``Documentation/FS25-lua-scripting-main/animals/husbandry/placeables/``.
The checker does not resolve i3D node indices, collision masks, animal-type
names, or growth-state names: those lookups need runtime objects that are
not in the local sources.

Not checked, and why:

* Pallet-trigger ``CollisionFlag.VEHICLE`` (PlaceableHusbandryPallets.lua
  around the ``getHasMaskFlagSet`` call). The bit is read from the loaded
  shape. No file in Documentation or fs25-claude-skill assigns the numeric
  value of ``CollisionFlag.VEHICLE``.
* Food unload triggers (PlaceableHusbandryFood.lua ``UnloadTrigger.createTriggers``).
  ``UnloadTrigger.registerTriggerXMLPaths`` has no function body in the local
  sources, so the child element that counts as a trigger is unknown.
* ``animals#type`` values, navigation-mesh class ids, and meadow growth-state
  names. The loader resolves those through ``animalSystem`` and
  ``fruitTypeDesc:getGrowthStateByName``, which are not tables in the local
  files.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.etree.ElementTree import Element

from app.core.models import Severity, ValidationReport
from app.knowledge.vanilla_materials import is_vanilla_fruit_type

_JUNK_DIRS = frozenset({".git", ".github"})

# PlaceableHusbandryMeadow.lua reads these three attributes only after
# getFruitTypeByName succeeds. A missing attribute is an xmlWarning.
_MEADOW_GROWTH_ATTRS: tuple[str, ...] = (
    "eatableStartGrowthState",
    "eatableEndGrowthState",
    "eatenGrowthState",
)


class HusbandryAuditor:
    """Read placeable XML and report husbandry attributes the loader rejects."""

    def __init__(self, mod_root: Path) -> None:
        self.mod_root = mod_root.resolve()

    def audit(self) -> ValidationReport:
        report = ValidationReport(target=self.mod_root)
        if not self.mod_root.is_dir():
            report.add(Severity.ERROR, f"HUS-000: Mod folder does not exist: {self.mod_root}")
            print(f"[HusbandryAuditor] {report.summary_line()}")
            return report

        found = False
        for path in _iter_xml(self.mod_root):
            location = _relative(self.mod_root, path)
            root = _parse_placeable(path, report, location)
            if root is None:
                continue
            husbandry = _direct_one(root, "husbandry")
            if husbandry is None:
                continue
            found = True
            _audit_animals(husbandry, report, location)
            _audit_feeding_robot(husbandry, report, location)
            _audit_fence(husbandry, report, location)
            _audit_meadow(husbandry, report, location)
            _audit_milk(husbandry, report, location)
            _audit_pallets(husbandry, report, location)

        if not found:
            report.add(
                Severity.INFO,
                "HUS-000: No placeable.husbandry XML in this folder.",
                location=self.mod_root.name,
            )
        print(f"[HusbandryAuditor] {report.summary_line()}")
        return report


def _audit_animals(husbandry: Element, report: ValidationReport, location: str) -> None:
    """PlaceableHusbandryAnimals.lua onLoad and loadDeliveryArea."""
    animals = _direct_one(husbandry, "animals")
    if animals is None:
        return
    # getValue("placeable.husbandry.animals#type") == nil, or a blank name
    # that cannot resolve, both set PlaceableLoadingState.ERROR.
    if _blank(animals.get("type")):
        report.add(
            Severity.ERROR,
            "HUS-001: placeable.husbandry.animals#type is missing. "
            "PlaceableHusbandryAnimals:onLoad logs 'Missing animal type!' and stops loading.",
            location=location,
        )
    areas = _direct_one(animals, "deliveryAreas")
    if areas is None:
        return
    for index, area in enumerate(_direct(areas, "deliveryArea"), start=1):
        where = f"{location} husbandry.animals.deliveryAreas.deliveryArea[{index}]"
        for attr, label in (
            ("startNode", "start node"),
            ("widthNode", "width node"),
            ("heightNode", "height node"),
        ):
            if attr in area.attrib:
                continue
            report.add(
                Severity.WARNING,
                f"HUS-002: Delivery area {label} is not set ({attr}). "
                "loadDeliveryArea returns false and the area is not used.",
                location=where,
            )


def _audit_feeding_robot(husbandry: Element, report: ValidationReport, location: str) -> None:
    """PlaceableHusbandryFeedingRobot.lua onLoad. Runs only when the element exists."""
    robot = _direct_one(husbandry, "feedingRobot")
    if robot is None:
        return
    where = f"{location} husbandry.feedingRobot"
    if "filename" not in robot.attrib:
        report.add(
            Severity.ERROR,
            "HUS-003: placeable.husbandry.feedingRobot#filename is missing. "
            "onLoad logs 'Feedingrobot filename missing' and sets the loading state to ERROR.",
            location=where,
        )
    # The schema default for #class is "". ClassUtil.getClassObject("") is nil.
    if _blank(robot.get("class")):
        report.add(
            Severity.ERROR,
            "HUS-004: placeable.husbandry.feedingRobot#class is missing. "
            "onLoad logs 'Feedingrobot class not defined' and sets the loading state to ERROR.",
            location=where,
        )
    if "linkNode" not in robot.attrib:
        report.add(
            Severity.ERROR,
            "HUS-005: placeable.husbandry.feedingRobot#linkNode is missing. "
            "onLoad logs 'Feedingrobot linkNode not defined' and sets the loading state to ERROR.",
            location=where,
        )
    splines = _direct_one(robot, "splines")
    if splines is None:
        return
    for index, spline in enumerate(_direct(splines, "spline"), start=1):
        if "node" in spline.attrib:
            continue
        report.add(
            Severity.WARNING,
            "HUS-006: Feeding robot spline#node is missing. "
            "onLoad logs 'Feedingrobot spline not defined' and stops reading further splines.",
            location=f"{where}.splines.spline[{index}]",
        )
        return


def _audit_fence(husbandry: Element, report: ValidationReport, location: str) -> None:
    """PlaceableHusbandryFence.lua section loop inside onFenceI3DLoaded.

    The loop runs only after fence#xmlFilename has been read. An omitted
    filename returns from onLoad before any section is inspected.
    """
    fence = _direct_one(husbandry, "fence")
    if fence is None:
        return
    if _blank(fence.get("xmlFilename")):
        return
    sections_node = _direct_one(fence, "sections")
    if sections_node is None:
        return
    sections = _direct(sections_node, "section")
    customizable_seen = False
    for index, section in enumerate(sections, start=1):
        where = f"{location} husbandry.fence.sections.section[{index}]"
        if customizable_seen:
            report.add(
                Severity.ERROR,
                "HUS-008: A customizable fence section is not the last section. "
                "onFenceI3DLoaded logs 'Customizable section needs to be the last section' "
                "and stops reading sections.",
                location=where,
            )
            return
        if "segmentId" not in section.attrib:
            report.add(
                Severity.ERROR,
                "HUS-007: Fence section#segmentId is missing. "
                "onFenceI3DLoaded logs 'Missing segment id'.",
                location=where,
            )
        if (section.get("customizable") or "").strip().lower() == "true":
            customizable_seen = True


def _audit_meadow(husbandry: Element, report: ValidationReport, location: str) -> None:
    """PlaceableHusbandryMeadow.lua fruitType loop."""
    meadow = _direct_one(husbandry, "meadow")
    if meadow is None:
        return
    for index, fruit in enumerate(_direct(meadow, "fruitType"), start=1):
        where = f"{location} husbandry.meadow.fruitType[{index}]"
        name = fruit.get("name")
        if _blank(name):
            report.add(
                Severity.WARNING,
                "HUS-009: Meadow fruitType#name is missing. "
                "onLoad calls getFruitTypeByName and skips the entry with no log line.",
                location=where,
            )
            continue
        # Growth-state warnings run only after getFruitTypeByName returns a
        # description. Restrict that to fruit names in the bundled vanilla list.
        if not is_vanilla_fruit_type(name):
            continue
        for attr in _MEADOW_GROWTH_ATTRS:
            if attr in fruit.attrib:
                continue
            report.add(
                Severity.WARNING,
                f"HUS-010: Meadow fruit type '{name}' is missing #{attr}. "
                "onLoad logs that the growth state is missing and skips the fruit.",
                location=where,
            )


def _audit_milk(husbandry: Element, report: ValidationReport, location: str) -> None:
    """PlaceableHusbandryMilk.lua milkingRobot loop. Each failure uses ``continue``."""
    milk = _direct_one(husbandry, "milk")
    if milk is None:
        return
    robots = _direct_one(milk, "milkingRobots")
    if robots is None:
        return
    for index, robot in enumerate(_direct(robots, "milkingRobot"), start=1):
        where = f"{location} husbandry.milk.milkingRobots.milkingRobot[{index}]"
        if "filename" not in robot.attrib:
            report.add(
                Severity.WARNING,
                "HUS-011: Milking robot#filename is missing. "
                "onLoad logs 'Milkingrobot filename missing' and skips the robot.",
                location=where,
            )
        if _blank(robot.get("class")):
            report.add(
                Severity.WARNING,
                "HUS-012: Milking robot#class is missing. "
                "onLoad logs 'Milkingrobot class not defined' and skips the robot.",
                location=where,
            )
        if "linkNode" not in robot.attrib:
            report.add(
                Severity.WARNING,
                "HUS-013: Milking robot#linkNode is missing. "
                "onLoad logs 'Milkingrobot linkNode not defined' and skips the robot.",
                location=where,
            )


def _audit_pallets(husbandry: Element, report: ValidationReport, location: str) -> None:
    """PlaceableHusbandryPallets.lua: a palletTrigger with no node is ignored."""
    pallets = _direct_one(husbandry, "pallets")
    if pallets is None:
        return
    for spawner_index, spawner in enumerate(_direct(pallets, "palletSpawner"), start=1):
        for trigger_index, trigger in enumerate(_direct(spawner, "palletTrigger"), start=1):
            if "node" in trigger.attrib:
                continue
            report.add(
                Severity.WARNING,
                "HUS-014: palletTrigger#node is missing. "
                "onLoad ignores the trigger and writes no log line.",
                location=(
                    f"{location} husbandry.pallets.palletSpawner[{spawner_index}]"
                    f".palletTrigger[{trigger_index}]"
                ),
            )


def _parse_placeable(path: Path, report: ValidationReport, location: str) -> Element | None:
    """Return the root when this file is a <placeable>. None otherwise."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        if "<placeable" in text and "<husbandry" in text:
            report.add(
                Severity.ERROR,
                "HUS-015: This file looks like a husbandry placeable but the XML does not parse.",
                location=location,
            )
        return None
    if _local(root.tag) != "placeable":
        return None
    return root


def _iter_xml(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name.lower() not in _JUNK_DIRS]
        for name in filenames:
            if name.lower().endswith(".xml"):
                yield Path(dirpath) / name


def _direct(parent: Element, tag: str) -> list[Element]:
    return [child for child in list(parent) if _local(child.tag) == tag]


def _direct_one(parent: Element, tag: str) -> Element | None:
    found = _direct(parent, tag)
    return found[0] if found else None


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name
