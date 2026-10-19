"""I3D scenegraph checks and the storeData generator."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.models import Severity  # noqa: E402
from app.generators.store_item_generator import StoreItemGenerator, StoreItemRequest  # noqa: E402
from app.validators.i3d_auditor import I3DAuditor  # noqa: E402
from app.validators.pipeline import SECTION_I3D, run_xml_validation_suite  # noqa: E402

failures: list[str] = []
passed = 0


def check(condition: bool, label: str) -> None:
    global passed
    if condition:
        passed += 1
        print(f"  ok    {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}")


def test_i3d_rules() -> None:
    print("I3D rules")
    with tempfile.TemporaryDirectory() as tmp:
        mod = Path(tmp)
        (mod / "modDesc.xml").write_text("<modDesc/>", encoding="utf-8")
        vehicle = mod / "vehicles"
        vehicle.mkdir()
        (vehicle / "item.xml").write_text(
            "<vehicle><base><filename>item.i3d</filename></base></vehicle>",
            encoding="utf-8",
        )
        (vehicle / "item.i3d").write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<i3D name="item" version="1.6">
    <Files>
        <File fileId="1" filename="Missing.dds"/>
        <File fileId="1" filename="Other.dds"/>
    </Files>
    <Materials>
        <Material name="body" materialId="1">
            <Texture fileId="9"/>
        </Material>
    </Materials>
    <Scene>
        <TransformGroup name="root" nodeId="4">
            <Shape name="body" shapeId="1" nodeId="4"/>
        </TransformGroup>
    </Scene>
</i3D>
""",
            encoding="utf-8",
        )
        report = I3DAuditor(mod).audit()
        codes = {issue.message.split(":", 1)[0] for issue in report.issues}
        check(codes >= {"I3D-001", "I3D-002", "I3D-003", "I3D-004"}, f"orphan, case, duplicate node and duplicate fileId ({sorted(codes)})")
        check(all(issue.severity == Severity.WARNING for issue in report.issues), "these i3D findings are warnings")
        check(report.passed, "warnings do not fail the section")


def test_store_xml() -> None:
    print("Store XML")
    basic = StoreItemGenerator.generate(StoreItemRequest(title="Sample Trailer", price="12500"))
    check("<storeData>" in basic.xml_text and basic.xml_text.strip().endswith("</storeData>"), "a plain request is a storeData document")
    check("<name>Sample Trailer</name>" in basic.xml_text, "title is written")
    check("<category>misc</category>" in basic.xml_text, "category defaults to misc")
    check("<price>12500</price>" in basic.xml_text, "price is written")
    check("<brand>" not in basic.xml_text, "an empty brand is omitted")

    full = StoreItemGenerator.generate(
        StoreItemRequest(
            title='A & B',
            brand="LIZARD",
            category="misc",
            image="store_icon.dds",
            washable=True,
            configuration_name='cab "wide"',
        )
    )
    check(full.xml_text.strip().endswith("</vehicle>"), "washable wraps storeData in vehicle")
    check("<washable />" in full.xml_text, "washable element is present")
    check("<name>A &amp; B</name>" in full.xml_text, "title characters are escaped")
    check('name="cab &quot;wide&quot;"' in full.xml_text, "configuration name is an attribute")
    check('allowChange=' not in full.xml_text, "allowChange keeps the schema default and is omitted")
    try:
        StoreItemGenerator.generate(StoreItemRequest(title="  "))
    except ValueError:
        check(True, "a blank title is rejected")
    else:
        check(False, "a blank title is rejected")


def test_samples() -> None:
    print("Samples")
    ok = run_xml_validation_suite(ROOT / "samples" / "sample_ok_mod")
    section = ok.section(SECTION_I3D)
    check(section is not None and section.passed, "sample_ok_mod i3D section passes")
    check(
        section is not None and not any(issue.severity == Severity.WARNING for issue in section.issues),
        "sample_ok_mod i3D section has no warnings",
    )
    broken = run_xml_validation_suite(ROOT / "samples" / "sample_broken_mod")
    broken_section = broken.section(SECTION_I3D)
    found = {issue.message.split(":", 1)[0] for issue in broken_section.issues} if broken_section else set()
    check({"I3D-001", "I3D-002", "I3D-003", "I3D-004"} <= found, f"sample_broken_mod reports i3D rules ({sorted(found)})")


def main() -> int:
    test_i3d_rules()
    test_store_xml()
    test_samples()
    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED, {passed} passed:")
        for label in failures:
            print(f"  - {label}")
        return 1
    print(f"ALL {passed} CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
