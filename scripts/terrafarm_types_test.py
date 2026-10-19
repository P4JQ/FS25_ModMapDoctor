"""TerraFarm ripper, excavatorRipper and discharger XML, from MACHINE_*.md."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.generators.terrafarm_generator import (  # noqa: E402
    MACHINE_TYPE_OPTIONS,
    TerraFarmGenerator,
    MachineConfigInput,
)

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


def generate(machine_type: str, **kwargs) -> ET.Element:
    config = MachineConfigInput(
        machine_type=machine_type,
        modes=list(kwargs.pop("modes", ["LOWER", "FLATTEN", "SMOOTH", "PAINT"])),
        vehicle_path="FS25_Demo/vehicles/machine.xml",
        machine_file_path="xml/machines/machine.xml",
        reference_node=kwargs.pop("reference_node", "posNodeRef"),
        work_width=kwargs.pop("work_width", "1.5"),
        **kwargs,
    )
    files = TerraFarmGenerator().generate_files(config)
    root = ET.fromstring(files.machine_xml)
    check(root.tag == "vehicle", f"{machine_type} root is vehicle")
    return root.find("machine")


def test_types_are_offered() -> None:
    print("Type list")
    ids = {type_id for _, type_id in MACHINE_TYPE_OPTIONS}
    check({"ripper", "excavatorRipper", "discharger"} <= ids, "three new type ids are offered")


def test_ripper() -> None:
    print("Ripper")
    machine = generate("ripper", offset="0 -0.2 0")
    check(machine is not None and machine.get("type") == "ripper", "type attribute is ripper")
    check(machine is not None and machine.get("fillUnitIndex") is None, "ripper has no fillUnitIndex")
    check(machine is not None and machine.get("shovelNodeIndex") is None, "ripper has no shovelNodeIndex")
    input_node = machine.find("input") if machine is not None else None
    check(
        input_node is not None and input_node.get("modes") == "LOWER FLATTEN SMOOTH PAINT",
        "ripper modes follow the documented example order",
    )
    work = machine.find("workArea") if machine is not None else None
    check(work is not None and work.get("referenceNode") == "posNodeRef", "ripper workArea referenceNode")
    check(work is not None and work.get("width") == "1.5", "ripper workArea width")
    check(work is not None and work.get("raycastDistance") is None, "ripper workArea has no raycastDistance")

    try:
        TerraFarmGenerator().generate_files(
            MachineConfigInput(
                machine_type="ripper",
                modes=["LOWER"],
                vehicle_path="a.xml",
                machine_file_path="b.xml",
                include_work_area=True,
            )
        )
        check(False, "ripper without referenceNode is rejected")
    except ValueError as exc:
        check("referenceNode" in str(exc), "ripper without referenceNode is rejected")


def test_excavator_ripper() -> None:
    print("Excavator ripper")
    machine = generate("excavatorRipper")
    check(machine is not None and machine.get("type") == "excavatorRipper", "type attribute is excavatorRipper")
    check(machine is not None and machine.find("input") is not None, "excavator ripper keeps the input block")
    check(machine is not None and machine.get("fillUnitIndex") is None, "excavator ripper has no fillUnitIndex")


def test_discharger() -> None:
    print("Discharger")
    machine = generate(
        "discharger",
        modes=["FLATTEN"],
        reference_node="",
        work_width="",
        fill_unit_index="2",
        discharge_node_index="3",
        raycast_distance="0.5",
        output_offset="0 0 1",
        offset="0 -0.15 0.75",
    )
    check(machine is not None and machine.get("type") == "discharger", "type attribute is discharger")
    check(machine is not None and machine.find("input") is None, "discharger has no input block even if modes were passed")
    check(machine is not None and machine.get("fillUnitIndex") == "2", "fillUnitIndex stays on machine")
    check(machine is not None and machine.get("dischargeNodeIndex") == "3", "dischargeNodeIndex stays on machine")
    work = machine.find("workArea") if machine is not None else None
    check(work is not None and work.get("raycastDistance") == "0.5", "raycastDistance is on workArea")
    check(work is not None and work.get("outputOffset") == "0 0 1", "outputOffset is on workArea")
    check(work is not None and work.get("offset") == "0 -0.15 0.75", "offset is on workArea")

    omitted = generate("discharger", modes=[], reference_node="", work_width="")
    check(omitted is not None and omitted.get("dischargeNodeIndex") is None, "empty dischargeNodeIndex is omitted")
    check(omitted is not None and omitted.find("workArea") is None, "empty discharger work area is omitted")


def main() -> int:
    test_types_are_offered()
    test_ripper()
    test_excavator_ripper()
    test_discharger()
    print(f"\n{passed} passed, {len(failures)} failed")
    if failures:
        for label in failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
