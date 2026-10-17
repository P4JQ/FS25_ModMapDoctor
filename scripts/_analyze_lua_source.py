"""One-off analysis of the vanilla FS25 Lua sources (FS25-lua-scripting-main).

Prints statistics used to derive the Lua auditor rules. Not part of the app.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"C:\FS25-GE10\Documentation\FS25-lua-scripting-main")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def main() -> None:
    files = sorted(ROOT.rglob("*.lua"))
    print(f"lua files: {len(files)}")
    texts = {f: read(f) for f in files}

    # ---- Event classes ------------------------------------------------
    event_re = re.compile(r"Class\(\s*(\w+)\s*,\s*(\w+)\s*\)")
    parents: Counter[str] = Counter()
    events: dict[str, Path] = {}
    for f, t in texts.items():
        for m in event_re.finditer(t):
            parents[m.group(2)] += 1
            if m.group(2) == "Event":
                events[m.group(1)] = f
    print(f"\nClass(X, Event) classes: {len(events)}")
    print("top parents:", parents.most_common(12))

    methods = ("emptyNew", "new", "readStream", "writeStream", "run", "sendEvent")
    missing: dict[str, list[str]] = defaultdict(list)
    for name, f in events.items():
        t = texts[f]
        for meth in methods:
            if not re.search(rf"function\s+{name}[.:]{meth}\s*\(", t):
                missing[meth].append(name)
    for meth in methods:
        print(f"  events lacking {meth:11s}: {len(missing[meth])}", missing[meth][:6])

    # How events create the base object
    ctor = Counter()
    for name, f in events.items():
        m = re.search(r"Event\.new\(\s*(\w+_mt)([^)]*)\)", texts[f])
        ctor[m.group(2).strip() if m else "NONE"] += 1
    print("Event.new(...) extra args:", ctor.most_common(6))

    # ---- Network patterns --------------------------------------------
    def count(pattern: str, only: list[Path] | None = None) -> int:
        rx = re.compile(pattern)
        return sum(1 for f in (only or files) if rx.search(texts[f]))

    patterns = {
        "InitEventClass": r"InitEventClass\s*\(",
        "g_server:broadcastEvent": r"g_server:broadcastEvent",
        "getServerConnection():sendEvent": r"getServerConnection\(\)\s*:\s*sendEvent",
        "connection:getIsServer()": r"connection\s*:\s*getIsServer\(\)",
        "g_server ~= nil": r"g_server\s*~=\s*nil",
        "self.isServer": r"\.isServer\b",
        "self.isClient": r"\.isClient\b",
        "NetworkUtil.writeNodeObject": r"NetworkUtil\.writeNodeObject",
        "streamWrite*": r"streamWrite\w+\(",
        "streamRead*": r"streamRead\w+\(",
        "raiseDirtyFlags": r"raiseDirtyFlags",
        "getNextDirtyFlag": r"getNextDirtyFlag",
        "registerXMLPaths": r"registerXMLPaths",
        "registerSavegameXMLPaths": r"registerSavegameXMLPaths",
        "loadFromXMLFile": r"loadFromXMLFile",
        "saveToXMLFile": r"saveToXMLFile",
        "onWriteStream": r"onWriteStream",
        "onReadStream": r"onReadStream",
        "onWriteUpdateStream": r"onWriteUpdateStream",
        "onReadUpdateStream": r"onReadUpdateStream",
        "prerequisitesPresent": r"prerequisitesPresent",
        "registerEventListeners": r"registerEventListeners",
        "SpecializationUtil.registerEventListener": r"SpecializationUtil\.registerEventListener",
        "SpecializationUtil.registerFunction": r"SpecializationUtil\.registerFunction",
        "SpecializationUtil.registerOverwrittenFunction": r"SpecializationUtil\.registerOverwrittenFunction",
        "SpecializationUtil.raiseEvent": r"SpecializationUtil\.raiseEvent",
        "XMLFile.load": r"XMLFile\.load",
        "XMLFile.loadIfExists": r"XMLFile\.loadIfExists",
        "xmlFile:getValue": r"xmlFile\s*:\s*getValue",
        "xmlFile:setValue": r"xmlFile\s*:\s*setValue",
    }
    print("\nfiles containing pattern:")
    for label, pat in patterns.items():
        print(f"  {label:50s} {count(pat)}")

    # ---- Legacy / deprecated API usage --------------------------------
    legacy = {
        "getXMLString(": r"\bgetXMLString\s*\(",
        "getXMLInt(": r"\bgetXMLInt\s*\(",
        "getXMLFloat(": r"\bgetXMLFloat\s*\(",
        "getXMLBool(": r"\bgetXMLBool\s*\(",
        "setXMLString(": r"\bsetXMLString\s*\(",
        "loadXMLFile(": r"\bloadXMLFile\s*\(",
        "saveXMLFile(": r"\bsaveXMLFile\s*\(",
        "createXMLFile(": r"\bcreateXMLFile\s*\(",
        "delete(xmlFile": r"\bdelete\s*\(\s*xmlFile",
        "Utils.getNoNil(": r"Utils\.getNoNil\s*\(",
        "Utils.getXMLValue / getNamedXML": r"Utils\.get(?:Named)?XML",
        "g_currentMission.missionInfo": r"g_currentMission\.missionInfo",
        "g_currentMission.environment": r"g_currentMission\.environment",
        "g_currentMission:addUpdateable": r"addUpdateable",
        "g_currentMission.player": r"g_currentMission\.player\b",
        "g_currentMission:getIsServer": r"g_currentMission:getIsServer",
        "g_currentMission:getIsClient": r"g_currentMission:getIsClient",
        "g_currentMission.isMasterUser": r"isMasterUser",
        "g_currentMission:getFarmId": r"g_currentMission:getFarmId",
        "g_i18n:getText": r"g_i18n:getText",
        "g_i18n.modEnvironments": r"modEnvironments",
        "g_modEventListeners": r"g_modEventListeners",
        "addModEventListener": r"addModEventListener",
        "Utils.overwrittenFunction": r"Utils\.overwrittenFunction",
        "Utils.appendedFunction": r"Utils\.appendedFunction",
        "Utils.prependedFunction": r"Utils\.prependedFunction",
        "Class(": r"\bClass\s*\(",
        "source(": r"\bsource\s*\(",
        "getfenv/setfenv": r"\b(?:getfenv|setfenv)\b",
        "table.getn": r"table\.getn",
        "unpack(": r"(?<![\w.])unpack\s*\(",
        "loadstring(": r"\bloadstring\s*\(",
        "string.gfind": r"string\.gfind",
        "math.mod": r"math\.mod\b",
        "g_gui:showInfoDialog": r"showInfoDialog",
        "InfoDialog.show": r"InfoDialog\.show",
        "Vehicle.registerXMLPaths": r"Vehicle\.registerXMLPaths",
        "g_asyncTaskManager": r"g_asyncTaskManager",
        "g_messageCenter:subscribe": r"g_messageCenter\s*:\s*subscribe\(",
        "MessageType.": r"MessageType\.",
        "g_farmManager:getFarmById": r"getFarmById",
        "g_currentMission.accessHandler": r"accessHandler",
        "Logging.deprecated": r"Logging\.deprecated",
        "deprecated (word)": r"(?i)\bdeprecated\b",
        "Logging.warning": r"Logging\.warning",
        "Logging.xmlWarning": r"Logging\.xmlWarning",
        "print(": r"(?<![\w.:])print\s*\(",
        "setTextColor / renderText": r"\brenderText\s*\(",
        "g_currentMission.hud": r"g_currentMission\.hud\b",
        "g_currentMission:showBlinkingWarning": r"showBlinkingWarning",
    }
    print("\nlegacy / API patterns (files containing / total occurrences):")
    for label, pat in legacy.items():
        rx = re.compile(pat)
        hits = [f for f in files if rx.search(texts[f])]
        occ = sum(len(rx.findall(texts[f])) for f in hits)
        sample = hits[0].relative_to(ROOT).as_posix() if hits else "-"
        print(f"  {label:42s} files={len(hits):4d} occurrences={occ:5d}  e.g. {sample}")

    # deprecation markers in the source (these name real legacy functions)
    print("\nlines mentioning 'deprecated' (first 40):")
    shown = 0
    rx = re.compile(r"(?i)deprecated")
    for f in files:
        for i, line in enumerate(texts[f].splitlines(), 1):
            if rx.search(line):
                print(f"  {f.relative_to(ROOT).as_posix()}:{i}: {line.strip()[:140]}")
                shown += 1
                if shown >= 40:
                    return


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
