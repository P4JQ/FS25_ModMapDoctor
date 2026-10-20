"""Tests for the fill-type and foliage fruit auditor.

Run from the project root:

    python scripts/fill_fruit_auditor_test.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.models import Severity, ValidationReport  # noqa: E402
from app.validators.fill_fruit_auditor import FillFruitAuditor  # noqa: E402
from app.validators.pipeline import (  # noqa: E402
    SECTION_FILL_FRUIT,
    run_xml_validation_suite,
)

failures: list[str] = []


def check(condition: bool, label: str) -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        failures.append(label)


def ids(report: ValidationReport) -> list[str]:
    found: list[str] = []
    for issue in report.issues:
        head = issue.message.split(":", 1)[0]
        if head.startswith(("FILL-", "FRUIT-")):
            found.append(head)
    return found


def write(mod: Path, relative: str, text: str) -> None:
    path = mod / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def audit(files: dict[str, str]) -> ValidationReport:
    with tempfile.TemporaryDirectory() as tmp:
        mod = Path(tmp)
        for name, text in files.items():
            write(mod, name, text)
        return FillFruitAuditor(mod).audit()


FILL = """<?xml version="1.0" encoding="utf-8" standalone="no" ?>
<map>
    <fillTypes>
        <fillType name="WHEAT"/>
        <fillType name="STRAW"/>
    </fillTypes>
    <fillTypeCategories>
        <fillTypeCategory name="GRAIN">WHEAT STONE</fillTypeCategory>
    </fillTypeCategories>
    <fillTypeConverters>
        <fillTypeConverter name="MOWER">
            <converter from="WHEAT" to="STRAW" factor="1"/>
        </fillTypeConverter>
    </fillTypeConverters>
</map>
"""

FRUIT = """<?xml version="1.0" encoding="utf-8" standalone="no" ?>
<map>
    <fruitTypes>
        <fruitType filename="foliage/wheat.xml"/>
    </fruitTypes>
    <fruitTypeCategories>
        <fruitTypeCategory name="GRAIN">WHEAT CANOLA</fruitTypeCategory>
    </fruitTypeCategories>
    <fruitTypeConverters>
        <fruitTypeConverter name="MOWER">
            <converter from="WHEAT" to="STRAW" factor="1"/>
        </fruitTypeConverter>
    </fruitTypeConverters>
</map>
"""

FOLIAGE = """<?xml version="1.0" encoding="utf-8" standalone="no" ?>
<foliageType>
    <fruitType name="WHEAT">
        <harvest><transition src="green" target="cut"/></harvest>
        <windrow fillType="STRAW"/>
    </fruitType>
    <foliageLayer numDensityMapChannels="4">
        <foliageState name="green" isGrowing="true" isDestructibleByWheel="true"/>
        <foliageState name="cut" isDestructedByWheel="true"/>
    </foliageLayer>
</foliageType>
"""

MAP = """<?xml version="1.0" encoding="utf-8" standalone="no" ?>
<map>
    <fillTypes filename="fillTypes.xml"/>
    <fruitTypes filename="fruitTypes.xml"/>
</map>
"""


def test_clean() -> None:
    print("Clean mod")
    report = audit({
        "maps/map.xml": MAP,
        "maps/fillTypes.xml": FILL,
        "maps/fruitTypes.xml": FRUIT,
        "maps/foliage/wheat.xml": FOLIAGE,
    })
    check(report.passed, "clean foliage mod passes")
    check(not ids(report), f"clean mod has no FILL/FRUIT findings ({ids(report)})")


def test_vanilla_catalog() -> None:
    print("Vanilla catalog")
    report = audit({
        "maps/fillTypes.xml": """<?xml version="1.0" encoding="utf-8" standalone="no" ?>
<map>
    <fillTypeCategories>
        <fillTypeCategory name="GROUND">STONE OAT SNOW</fillTypeCategory>
    </fillTypeCategories>
    <fillTypeConverters>
        <fillTypeConverter name="MOWER">
            <converter from="WHEAT" to="STRAW" factor="1"/>
        </fillTypeConverter>
    </fillTypeConverters>
</map>
""",
        "maps/fruitTypes.xml": """<?xml version="1.0" encoding="utf-8" standalone="no" ?>
<map>
    <fruitTypes>
        <fruitType filename="foliage/rice.xml"/>
    </fruitTypes>
    <fruitTypeCategories>
        <fruitTypeCategory name="GRAIN">WHEAT BARLEY RICE</fruitTypeCategory>
    </fruitTypeCategories>
</map>
""",
        "maps/foliage/rice.xml": """<?xml version="1.0" encoding="utf-8" standalone="no" ?>
<foliageType>
    <fruitType name="rice">
        <windrow fillType="STRAW"/>
    </fruitType>
    <foliageLayer>
        <foliageState name="green"/>
    </foliageLayer>
</foliageType>
""",
    })
    found = set(ids(report))
    check("FILL-003" not in found, "game fill types do not raise FILL-003")
    retired = audit({
        "maps/fillTypes.xml": """<?xml version="1.0" encoding="utf-8" standalone="no" ?>
<map>
    <fillTypeCategories>
        <fillTypeCategory name="OLD">OATS GRAVEL SAND COFFEE DIRT</fillTypeCategory>
    </fillTypeCategories>
</map>
""",
    })
    retired_ids = retired.issues
    retired_text = " ".join(issue.message for issue in retired_ids)
    check(
        all(f"'{name}'" in retired_text for name in ("OATS", "GRAVEL", "SAND", "COFFEE", "DIRT")),
        "names absent from maps_fillTypes.xml are unknown",
    )
    check("'" + "OAT" + "'" not in retired_text, "the game fill type OAT is not reported")
    check("FRUIT-005" not in found, "vanilla fruit RICE does not raise FRUIT-005")
    check("FRUIT-006" not in found, "vanilla fruits in a category do not raise FRUIT-006")
    check("FRUIT-010" not in found, "vanilla windrow STRAW does not raise FRUIT-010")
    check(report.passed and "FILL-004" not in found, "vanilla converter endpoints are accepted")


def test_rules() -> None:
    print("Loader rules")
    broken_fill = """<?xml version="1.0" encoding="utf-8" standalone="no" ?>
<map>
    <fillTypes>
        <fillType name="wheat"/>
        <fillType name="BAD NAME"/>
    </fillTypes>
    <fillTypeCategories>
        <fillTypeCategory name="GRAIN">WHEAT MISSINGCROP</fillTypeCategory>
    </fillTypeCategories>
    <fillTypeConverters>
        <fillTypeConverter name="MOWER">
            <converter from="WHEAT" to="STRAW"/>
            <converter from="NOPE" to="ALSO_NOPE" factor="1"/>
        </fillTypeConverter>
    </fillTypeConverters>
    <fillTypeSounds>
        <fillTypeSound fillTypes="NOT_A_FILL"/>
    </fillTypeSounds>
</map>
"""
    broken_fruit = """<?xml version="1.0" encoding="utf-8" standalone="no" ?>
<map>
    <fruitTypes>
        <fruitType/>
        <fruitType filename="foliage/wheat.xml"/>
        <fruitType filename="foliage/purplecrop.xml"/>
        <fruitType filename="foliage/missing.xml"/>
    </fruitTypes>
    <fruitTypeCategories>
        <fruitTypeCategory name="GRAIN">PURPLECROP</fruitTypeCategory>
    </fruitTypeCategories>
    <fruitTypeConverters>
        <fruitTypeConverter name="MOWER">
            <converter from="PURPLECROP" to="NOT_A_FILL"/>
        </fruitTypeConverter>
    </fruitTypeConverters>
</map>
"""
    wheat = """<?xml version="1.0" encoding="utf-8" standalone="no" ?>
<foliageType>
    <fruitType name="WHEAT">
        <harvest><transition src="green" target="missingState"/></harvest>
        <windrow fillType="NOT_STRAW"/>
    </fruitType>
    <foliageLayer>
        <foliageState name="green" isWithered="true" isDestructibleByWheel="true"/>
        <foliageState name="dead" isWithered="true"/>
    </foliageLayer>
</foliageType>
"""
    purple = """<?xml version="1.0" encoding="utf-8" standalone="no" ?>
<foliageType>
    <fruitType name="PURPLECROP"/>
    <foliageLayer>
        <foliageState name="green"/>
    </foliageLayer>
</foliageType>
"""
    report = audit({
        "maps/fillTypes.xml": broken_fill,
        "maps/fruitTypes.xml": broken_fruit,
        "maps/foliage/wheat.xml": wheat,
        "maps/foliage/purplecrop.xml": purple,
    })
    found = set(ids(report))
    expected = {
        "FILL-002", "FILL-003", "FILL-004", "FILL-006", "FILL-007",
        "FRUIT-001", "FRUIT-002", "FRUIT-005", "FRUIT-006", "FRUIT-007",
        "FRUIT-008", "FRUIT-009", "FRUIT-010", "FRUIT-011",
    }
    check(expected <= found, f"expected rules present (missing {sorted(expected - found)})")
    # The fruit is ignored before its windrow is read, so PURPLECROP must not raise FRUIT-010.
    purple_lines = [
        issue.message for issue in report.issues
        if "purplecrop.xml" in (issue.location or "") and issue.message.startswith("FRUIT-010")
    ]
    check(not purple_lines, "rejected fruit does not also report windrow warnings")
    # Lower case still registers: MISSINGCROP is unknown, WHEAT itself is not.
    unknown = [issue.message for issue in report.issues if issue.message.startswith("FILL-003")]
    check(len(unknown) == 1 and "MISSINGCROP" in unknown[0], "category warning names the missing fill type")
    check(
        any(issue.severity == Severity.INFO and "WHEAT" in issue.message for issue in report.issues),
        "mixed-case fill type is reported as stored upper-case",
    )
    check(report.passed, "warnings do not fail the section")


def test_samples_and_pipeline() -> None:
    print("Samples and pipeline")
    ok = run_xml_validation_suite(ROOT / "samples" / "sample_ok_mod")
    section = ok.section(SECTION_FILL_FRUIT)
    check(section is not None and section.passed and not ids(section), "sample_ok_mod fill/fruit section is clean")
    check(len(ok.sections) == 8, "suite has eight sections")

    broken = run_xml_validation_suite(ROOT / "samples" / "sample_broken_mod")
    broken_section = broken.section(SECTION_FILL_FRUIT)
    found = set(ids(broken_section)) if broken_section else set()
    check("FILL-004" in found and "FRUIT-008" in found, "sample_broken_mod reports converter and state findings")
    check(not broken.passed, "sample_broken_mod suite still fails")


def main() -> int:
    test_clean()
    test_vanilla_catalog()
    test_rules()
    test_samples_and_pipeline()
    print("-" * 60)
    print("ALL CHECKS PASSED" if not failures else f"{len(failures)} CHECK(S) FAILED: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
