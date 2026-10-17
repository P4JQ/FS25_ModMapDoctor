"""One-off extractor: deprecated absolute vehicle XML paths -> JSON knowledge file.

Source of truth: every ``XMLUtil.checkDeprecatedXMLElements(xml, "old", "new")``
call in the vanilla scripts (FS25-lua-scripting-main) and in the generated API
docs (docs/script). Only calls where the old path is an absolute string literal
starting with ``vehicle.`` are kept; relative keys built at runtime are skipped.

Usage: python scripts/_extract_deprecated_xml.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

DOC_ROOT = Path(r"C:\FS25-GE10\Documentation")
OUTPUT = Path(__file__).resolve().parents[1] / "app" / "knowledge" / "lua_deprecated_xml_paths.json"

_CALL = re.compile(
    r"checkDeprecatedXMLElements\(\s*[\w.:]+\s*,\s*\"(vehicle\.[^\"]+)\"\s*"
    r"(?:,\s*\"([^\"]*)\")?\s*\)\s*(?:--\s*(FS\d+\s*to\s*FS\d+))?"
)


def main() -> None:
    found: dict[str, dict[str, str | None]] = {}
    files = [
        *DOC_ROOT.joinpath("FS25-lua-scripting-main").rglob("*.lua"),
        *DOC_ROOT.joinpath("docs", "script").rglob("*.md"),
    ]
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _CALL.finditer(text):
            old, new, era = match.group(1), match.group(2), match.group(3)
            era = re.sub(r"\s+", " ", era) if era else None
            entry = found.setdefault(old, {"new": new or None, "era": era})
            if entry["era"] is None and era:
                entry["era"] = era

    # Drop paths the vanilla code itself still reads (backward-compatibility
    # fallbacks such as Motorized's xmlFile:hasProperty("vehicle.motor")): a mod
    # doing the same is consistent with vanilla, not outdated.
    still_read: set[str] = set()
    literal = re.compile(r'"([^"\n]+)"')
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in literal.finditer(text):
            value = match.group(1)
            if value in found and "checkDeprecatedXMLElements" not in text[max(0, match.start() - 240) : match.start()]:
                still_read.add(value)
    for value in sorted(still_read):
        print(f"  keeping out (vanilla still reads it): {value}")
        found.pop(value, None)

    rows = [
        {"old": old, "new": data["new"], "era": data["era"]}
        for old, data in sorted(found.items())
    ]
    OUTPUT.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(f"{len(rows)} deprecated vehicle XML paths -> {OUTPUT}")
    for row in rows[:8]:
        print("  ", row)


if __name__ == "__main__":
    main()
