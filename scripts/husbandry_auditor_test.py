"""Husbandry placeable attribute checks. No node or collision-mask lookups."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.models import Severity  # noqa: E402
from app.validators.husbandry_auditor import HusbandryAuditor  # noqa: E402
from app.validators.pipeline import SECTION_HUSBANDRY, run_xml_validation_suite  # noqa: E402

failures: list[str] = []
passed = 0

CLEAN = """<?xml version="1.0" encoding="utf-8"?>
<placeable>
  <husbandry>
    <animals type="COW">
      <deliveryAreas>
        <deliveryArea startNode="0>0" widthNode="0>1" heightNode="0>2"/>
      </deliveryAreas>
    </animals>
    <feedingRobot filename="robot.xml" class="FeedingRobot" linkNode="0>3">
      <splines>
        <spline node="0>4" direction="1"/>
      </splines>
    </feedingRobot>
    <fence xmlFilename="fence.xml">
      <sections>
        <section segmentId="gate"/>
        <section segmentId="panel" customizable="true"/>
      </sections>
    </fence>
    <meadow>
      <fruitType name="GRASS" eatableStartGrowthState="green"
                 eatableEndGrowthState="harvestReady" eatenGrowthState="eaten"/>
      <fruitType name="MY_CUSTOM_GRASS"/>
    </meadow>
    <milk>
      <milkingRobots>
        <milkingRobot filename="milk.xml" class="MilkingRobot" linkNode="0>5"/>
      </milkingRobots>
    </milk>
    <pallets>
      <palletSpawner>
        <palletTrigger node="0>6"/>
      </palletSpawner>
    </pallets>
  </husbandry>
</placeable>
"""

BROKEN = """<?xml version="1.0" encoding="utf-8"?>
<placeable>
  <husbandry>
    <animals type=" ">
      <deliveryAreas>
        <deliveryArea widthNode="0>1"/>
      </deliveryAreas>
    </animals>
    <feedingRobot class="  ">
      <splines>
        <spline direction="1"/>
      </splines>
    </feedingRobot>
    <fence>
      <sections>
        <section/>
      </sections>
    </fence>
    <meadow>
      <fruitType eatableStartGrowthState="green"/>
      <fruitType name="WHEAT" eatenGrowthState="cut"/>
    </meadow>
    <milk>
      <milkingRobots>
        <milkingRobot class=""/>
      </milkingRobots>
    </milk>
    <pallets>
      <palletSpawner>
        <palletTrigger/>
      </palletSpawner>
    </pallets>
  </husbandry>
</placeable>
"""

FENCE_ORDER = """<?xml version="1.0" encoding="utf-8"?>
<placeable>
  <husbandry>
    <fence xmlFilename="fence.xml">
      <sections>
        <section segmentId="panel" customizable="true"/>
        <section segmentId="after"/>
        <section/>
      </sections>
    </fence>
  </husbandry>
</placeable>
"""

UNKNOWN_TYPE = """<?xml version="1.0" encoding="utf-8"?>
<placeable>
  <husbandry>
    <animals type="NOT_A_REAL_ANIMAL"/>
  </husbandry>
</placeable>
"""


def check(condition: bool, label: str) -> None:
    global passed
    if condition:
        passed += 1
        print(f"  ok    {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}")


def _ids(report) -> list[str]:
    found: list[str] = []
    for issue in report.issues:
        token = issue.message.split(":", 1)[0]
        found.append(token)
    return found


def _write(mod: Path, name: str, text: str) -> None:
    (mod / name).write_text(text, encoding="utf-8")


def test_rules() -> None:
    print("Husbandry rules")
    with tempfile.TemporaryDirectory() as tmp:
        mod = Path(tmp)
        _write(mod, "clean.xml", CLEAN)
        clean = HusbandryAuditor(mod).audit()
        clean_ids = _ids(clean)
        check(clean.passed and clean.warning_count == 0, "complete husbandry XML has no errors or warnings")
        check("HUS-001" not in clean_ids, "known-looking animal type is not checked against a catalog")
        check("HUS-010" not in clean_ids, "custom meadow fruit without growth states is not flagged")
        check("HUS-014" not in clean_ids, "pallet trigger with a node is not a mask error")

        mod2 = Path(tmp) / "broken"
        mod2.mkdir()
        _write(mod2, "barn.xml", BROKEN)
        _write(mod2, "vehicle.xml", "<vehicle><base><filename>x.i3d</filename></base></vehicle>")
        broken = HusbandryAuditor(mod2).audit()
        ids = _ids(broken)
        check("HUS-001" in ids and broken.error_count >= 1, "blank animals#type is an error")
        check(ids.count("HUS-002") == 2, "delivery area reports each missing node attribute")
        check("HUS-003" in ids and "HUS-004" in ids and "HUS-005" in ids, "feeding robot requires filename, class, and linkNode")
        check("HUS-006" in ids, "feeding robot spline without a node is a warning")
        check("HUS-007" not in ids, "fence sections are ignored when xmlFilename is omitted")
        check("HUS-009" in ids, "meadow fruitType without a name is a warning")
        check("HUS-010" in ids, "vanilla meadow fruit missing a growth attribute is a warning")
        wheat = [issue for issue in broken.issues if "WHEAT" in issue.message]
        check(len(wheat) == 2, "WHEAT reports only the two missing growth attributes")
        check(all(issue.severity == Severity.WARNING for issue in wheat), "meadow growth findings stay warnings")
        check("HUS-011" in ids and "HUS-012" in ids and "HUS-013" in ids, "milking robot skips missing filename, class, and linkNode")
        check("HUS-014" in ids, "pallet trigger without a node is a warning")
        check(all(issue.severity == Severity.WARNING for issue in broken.issues if issue.message.startswith("HUS-014")), "pallet trigger finding is a warning")

        mod3 = Path(tmp) / "fence"
        mod3.mkdir()
        _write(mod3, "fencePlaceable.xml", FENCE_ORDER)
        fence = HusbandryAuditor(mod3).audit()
        fence_ids = _ids(fence)
        check("HUS-008" in fence_ids, "customizable fence section must be last")
        check(fence_ids.count("HUS-008") == 1, "the loader stops at the first section after a customizable one")
        check("HUS-007" not in fence_ids, "a section after the customizable one is not also a missing-id error")

        mod4 = Path(tmp) / "type"
        mod4.mkdir()
        _write(mod4, "animals.xml", UNKNOWN_TYPE)
        unknown = HusbandryAuditor(mod4).audit()
        check(unknown.passed and unknown.warning_count == 0, "an unknown animal type name is not flagged")

        mod5 = Path(tmp) / "bad"
        mod5.mkdir()
        _write(mod5, "broken.xml", "<placeable><husbandry>")
        bad = HusbandryAuditor(mod5).audit()
        check("HUS-015" in _ids(bad) and not bad.passed, "unparsed husbandry placeable is an error")


def test_samples() -> None:
    print("Samples")
    ok = run_xml_validation_suite(ROOT / "samples" / "sample_ok_mod")
    section = ok.section(SECTION_HUSBANDRY)
    check(section is not None and section.passed, "sample_ok_mod Husbandry section passes")
    check(
        section is not None and section.warning_count == 0,
        "sample_ok_mod Husbandry section has no warnings",
    )
    check(ok.passed, "sample_ok_mod suite still passes")
    check(len(ok.sections) == 7, "suite has seven sections")


def main() -> int:
    test_rules()
    test_samples()
    print(f"\n{passed} passed, {len(failures)} failed")
    if failures:
        print("FAILED:")
        for label in failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
