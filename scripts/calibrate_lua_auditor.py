"""Calibrate the Lua auditor against vanilla FS25 code.

Vanilla code is the reference: the rules should produce (almost) no findings on
it. This script runs ``analyze_lua`` over

* every .lua file in Documentation/FS25-lua-scripting-main (267 files; note that
  many functions in those files were blanked out by the repository author, so
  "function is missing" rules naturally fire there), and
* the code blocks of every class page in Documentation/docs/script (events,
  vehicle/placeable specializations, ...), rebuilt into pseudo-Lua.

It prints, per rule, the findings split by corpus plus samples. Use it whenever
a rule is added or changed. Usage:

    python scripts/calibrate_lua_auditor.py [--samples N] [--rule ID] [--corpus lua-src|docs]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.validators.lua_auditor import Finding, analyze_lua  # noqa: E402

DOC_ROOT = Path(r"C:\FS25-GE10\Documentation")
LUA_SRC = DOC_ROOT / "FS25-lua-scripting-main"
DOC_SCRIPT = DOC_ROOT / "docs" / "script"

_FENCE = re.compile(r"```lua\n(.*?)```", re.DOTALL)
_PARENT = re.compile(r"\*\*Parent\*\*\s*\n\s*\n>\s*\[(\w+)\]")
_TITLE = re.compile(r"^##\s+(\w+)", re.MULTILINE)


def md_to_pseudo_lua(text: str) -> str:
    """Rebuild Lua from a generated API page (undoing the md formatting noise)."""
    code = "\n".join(_FENCE.findall(text))
    code = code.replace("~ =", "~=").replace("= =", "==").replace("< =", "<=").replace("> =", ">=")
    code = re.sub(r"(\w) _mt\b", r"\1_mt", code)
    title = _TITLE.search(text)
    parent = _PARENT.search(text)
    if title and parent and parent.group(1) == "Event":
        name = title.group(1)
        code = f"local {name}_mt = Class({name}, Event)\n" + code
    return code


def corpus(which: str | None) -> list[tuple[str, str, str]]:
    """(label, corpus name, lua text)."""
    items: list[tuple[str, str, str]] = []
    if which in (None, "lua-src"):
        for path in sorted(LUA_SRC.rglob("*.lua")):
            items.append(
                (
                    path.relative_to(DOC_ROOT).as_posix(),
                    "lua-src",
                    path.read_text(encoding="utf-8", errors="replace"),
                )
            )
    if which in (None, "docs"):
        for path in sorted(DOC_SCRIPT.rglob("*.md")):
            text = path.read_text(encoding="utf-8", errors="replace")
            items.append((path.relative_to(DOC_ROOT).as_posix(), "docs", md_to_pseudo_lua(text)))
    return items


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=6)
    parser.add_argument("--rule", default=None)
    parser.add_argument("--corpus", choices=("lua-src", "docs"), default=None)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    items = corpus(args.corpus)
    by_rule: dict[str, list[tuple[str, str, Finding]]] = defaultdict(list)
    totals: Counter[str] = Counter()
    for label, name, text in items:
        analysis = analyze_lua(text)
        totals[f"{name} files"] += 1
        totals[f"{name} events"] += len(analysis.event_classes)
        totals[f"{name} specializations"] += len(analysis.spec_classes)
        for finding in analysis.findings:
            by_rule[finding.rule_id].append((label, name, finding))

    print(dict(totals), "\n")
    for rule_id in sorted(by_rule):
        if args.rule and rule_id != args.rule:
            continue
        hits = by_rule[rule_id]
        split = Counter((name, f.severity.value) for _l, name, f in hits)
        pretty = ", ".join(f"{n}/{s}={c}" for (n, s), c in sorted(split.items()))
        print(f"== {rule_id}: {len(hits)} finding(s)  [{pretty}]")
        for label, _name, finding in hits[: args.samples]:
            print(f"   {label}:{finding.line}  {finding.message[:230]}")
        print()
    if not by_rule:
        print("No findings at all on vanilla code.")


if __name__ == "__main__":
    main()
