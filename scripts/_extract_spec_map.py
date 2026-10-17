"""One-off helper: build XML-block -> specialization map from GE10 docs."""

from __future__ import annotations

import json
import re
from pathlib import Path

DOCS = Path(r"C:\FS25-GE10\Documentation\docs\script\Specializations")
OUT = Path(__file__).resolve().parents[1] / "app" / "knowledge" / "xml_block_to_specialization.json"

PATTERN = re.compile(r'"vehicle\.([A-Za-z_][A-Za-z0-9_]*)')


def to_spec_name(class_name: str) -> str:
    return class_name[0].lower() + class_name[1:]


def main() -> None:
    block_to_files: dict[str, set[str]] = {}
    all_specs: list[str] = []

    for md in sorted(DOCS.glob("*.md")):
        if md.stem.startswith("Placeable") or md.stem.startswith("_"):
            continue
        all_specs.append(to_spec_name(md.stem))
        text = md.read_text(encoding="utf-8", errors="ignore")
        for block in PATTERN.findall(text):
            block_to_files.setdefault(block, set()).add(md.stem)

    mapping: dict[str, str] = {}
    ambiguous: dict[str, list[str]] = {}

    for block, classes in sorted(block_to_files.items()):
        exact = [c for c in classes if to_spec_name(c) == block]
        if len(exact) == 1:
            mapping[block] = to_spec_name(exact[0])
            continue
        # Single class that uniquely owns this block name as its primary path
        if len(classes) == 1:
            mapping[block] = to_spec_name(next(iter(classes)))
            continue
        ambiguous[block] = sorted(to_spec_name(c) for c in classes)

    # Direct 1:1 for every vehicle specialization class (even if schema uses nested paths)
    for spec in all_specs:
        mapping.setdefault(spec, spec)

    # Manual overrides for shared / nested roots
    mapping.update(
        {
            # Shared AI root — multiple specs; validate against any ai* presence via separate logic
            "machine": "machine",  # TerraFarm external
        }
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "xmlBlockToSpecialization": mapping,
        "knownVehicleSpecializations": sorted(set(all_specs)),
        "ambiguousBlocks": ambiguous,
        "source": str(DOCS),
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"mapped={len(mapping)} specs={len(all_specs)} ambiguous={len(ambiguous)}")


if __name__ == "__main__":
    main()
