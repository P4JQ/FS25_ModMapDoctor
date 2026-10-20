"""Tests for the Lua auditor (no GUI needed).

Run from the project root:

    python scripts/lua_auditor_test.py

Three kinds of checks:

1. Synthetic Lua snippets: every rule must fire on the bad pattern and stay
   silent on the vanilla-shaped pattern.
2. Vanilla regression: the stream-comparison and legacy-API rules must report
   nothing on the vanilla FS25 sources (these rules were calibrated on them).
3. End-to-end: ``LuaAuditor`` on temporary mods and on the two sample mods.

NOTE: the reference sources have many function bodies blanked out, so the
"something is missing" rules cannot be validated against them; those rules are
covered by the synthetic cases here only.
"""

from __future__ import annotations

import sys
import tempfile
import textwrap
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.models import Severity, ValidationReport  # noqa: E402
from app.validators.lua_auditor import (  # noqa: E402
    LuaAnalysis,
    LuaAuditor,
    analyze_lua,
    stream_signature,
    describe_stream_mismatch,
)
from app.validators.pipeline import (  # noqa: E402
    SECTION_LUA,
    run_xml_validation_suite,
)

LUA_SRC = ROOT.parent / "Documentation" / "FS25-lua-scripting-main"

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


def ids(analysis: LuaAnalysis) -> list[str]:
    return [finding.rule_id for finding in analysis.findings]


def lua(text: str) -> LuaAnalysis:
    return analyze_lua(textwrap.dedent(text))


# ----------------------------------------------------------------------
# Building blocks for synthetic events
# ----------------------------------------------------------------------

GOOD_EVENT = """
MyEvent = {}
local MyEvent_mt = Class(MyEvent, Event)

function MyEvent.emptyNew()
    return Event.new(MyEvent_mt)
end

function MyEvent.new(object, amount)
    local self = MyEvent.emptyNew()
    self.object = object
    self.amount = amount
    return self
end

function MyEvent:readStream(streamId, connection)
    self.object = NetworkUtil.readNodeObject(streamId)
    self.amount = streamReadInt32(streamId)
    self:run(connection)
end

function MyEvent:writeStream(streamId, connection)
    NetworkUtil.writeNodeObject(streamId, self.object)
    streamWriteInt32(streamId, self.amount)
end

function MyEvent:run(connection)
    if not connection:getIsServer() then
        g_server:broadcastEvent(MyEvent.new(self.object, self.amount), nil, connection, self.object)
    end
end

function MyEvent.sendEvent(object, amount, noEventSend)
    if noEventSend == nil or noEventSend == false then
        if g_server ~= nil then
            g_server:broadcastEvent(MyEvent.new(object, amount), nil, nil, object)
        else
            g_client:getServerConnection():sendEvent(MyEvent.new(object, amount))
        end
    end
end
"""


def test_events() -> None:
    print("Events")
    check(ids(lua(GOOD_EVENT)) == [], "vanilla-shaped event: no findings")

    no_empty_new = GOOD_EVENT.replace(
        "function MyEvent.emptyNew()\n    return Event.new(MyEvent_mt)\nend",
        "function MyEvent.helper()\n    return 1\nend",
    ).replace("MyEvent.emptyNew()", "Event.new(MyEvent_mt)")
    found = lua(no_empty_new)
    check("LUA-EVT-001" in ids(found), "missing emptyNew -> LUA-EVT-001")
    check(
        any(f.severity is Severity.ERROR for f in found.findings if f.rule_id == "LUA-EVT-001"),
        "LUA-EVT-001 is an ERROR",
    )

    only_write = GOOD_EVENT.replace("function MyEvent:readStream", "function MyEvent:readStreamX")
    check("LUA-EVT-002" in ids(lua(only_write)), "writeStream without readStream -> LUA-EVT-002")

    swapped = GOOD_EVENT.replace(
        "    self.object = NetworkUtil.readNodeObject(streamId)\n    self.amount = streamReadInt32(streamId)",
        "    self.amount = streamReadInt32(streamId)\n    self.object = NetworkUtil.readNodeObject(streamId)",
    )
    check("LUA-EVT-004" in ids(lua(swapped)), "swapped read order -> LUA-EVT-004")

    wrong_type = GOOD_EVENT.replace("streamReadInt32", "streamReadInt8")
    check("LUA-EVT-004" in ids(lua(wrong_type)), "Int32 written / Int8 read -> LUA-EVT-004")

    missing_read = GOOD_EVENT.replace("    self.amount = streamReadInt32(streamId)\n", "")
    check("LUA-EVT-004" in ids(lua(missing_read)), "value written but never read -> LUA-EVT-004")

    node_id = GOOD_EVENT.replace("NetworkUtil.readNodeObject(", "NetworkUtil.readNodeObjectId(")
    check("LUA-EVT-004" not in ids(lua(node_id)), "writeNodeObject / readNodeObjectId is accepted")

    # Vanilla reads a loop with a different shape than it writes it.
    looped = """
        LoopEvent = {}
        local LoopEvent_mt = Class(LoopEvent, Event)
        function LoopEvent.emptyNew() return Event.new(LoopEvent_mt) end
        function LoopEvent:readStream(streamId, connection)
            local n = streamReadUInt8(streamId)
            for i = 1, n do
                self.values[i] = streamReadInt32(streamId)
            end
            self:run(connection)
        end
        function LoopEvent:writeStream(streamId, connection)
            streamWriteUInt8(streamId, #self.values)
            for _, value in ipairs(self.values) do
                streamWriteInt32(streamId, value)
            end
        end
        function LoopEvent:run(connection) end
    """
    check("LUA-EVT-004" not in ids(lua(looped)), "loops are not compared as a flat list")

    tokens_w = stream_signature("streamWriteInt8(s, 1) streamWriteBool(s, x)", "write")
    tokens_r = stream_signature("streamReadInt8(s) streamReadBool(s)", "read")
    check(describe_stream_mismatch(tokens_w, tokens_r) is None, "stream_signature: matching pair")

    # Client -> server events must be relayed by run().
    no_relay = GOOD_EVENT.replace(
        "    if not connection:getIsServer() then\n"
        "        g_server:broadcastEvent(MyEvent.new(self.object, self.amount), nil, connection, self.object)\n"
        "    end",
        "    self.object:setAmount(self.amount)",
    )
    check("LUA-EVT-005" in ids(lua(no_relay)), "client request never relayed -> LUA-EVT-005")
    check("LUA-EVT-005" not in ids(lua(GOOD_EVENT)), "relaying run() -> no LUA-EVT-005")

    server_only = no_relay.replace(
        "            g_client:getServerConnection():sendEvent(MyEvent.new(object, amount))",
        "            -- nothing: server only",
    )
    found = lua(server_only)
    check("LUA-EVT-006" in ids(found), "sendEvent without client branch -> LUA-EVT-006")
    check("LUA-EVT-005" not in ids(found), "no client->server path -> no LUA-EVT-005")

    client_only = GOOD_EVENT[: GOOD_EVENT.index("function MyEvent.sendEvent")] + """
function MyEvent.sendEvent(object, amount)
    g_client:getServerConnection():sendEvent(MyEvent.new(object, amount))
end
"""
    check("LUA-EVT-006" in ids(lua(client_only)), "sendEvent without server branch -> LUA-EVT-006")

    wrong_mt = GOOD_EVENT.replace("Event.new(MyEvent_mt)\nend", "Event.new(Other_mt)\nend", 1)
    check("LUA-EVT-008" in ids(lua(wrong_mt)), "emptyNew with wrong metatable -> LUA-EVT-008")

    no_run = GOOD_EVENT.replace("function MyEvent:run(connection)", "function MyEvent:runX(connection)")
    check("LUA-EVT-003" in ids(lua(no_run)), "event without run() -> LUA-EVT-003 (info)")

    # Text inside comments and strings must never be analysed.
    commented = "-- MyEvent = Class(MyEvent, Event)\n--[[ g_currentMission.player ]]\nlocal s = 'g_currentMission.controlledVehicle'\n"
    check(ids(lua(commented)) == [], "comments and strings are ignored")


# ----------------------------------------------------------------------
# Specializations
# ----------------------------------------------------------------------

GOOD_SPEC = """
MySpec = {}

function MySpec.prerequisitesPresent(specializations)
    return true
end

function MySpec.registerEventListeners(vehicleType)
    SpecializationUtil.registerEventListener(vehicleType, "onLoad", MySpec)
    SpecializationUtil.registerEventListener(vehicleType, "onReadStream", MySpec)
    SpecializationUtil.registerEventListener(vehicleType, "onWriteStream", MySpec)
    SpecializationUtil.registerEventListener(vehicleType, "onReadUpdateStream", MySpec)
    SpecializationUtil.registerEventListener(vehicleType, "onWriteUpdateStream", MySpec)
end

function MySpec:onLoad(savegame)
    self.spec_mySpec = {}
    self.spec_mySpec.dirtyFlag = self:getNextDirtyFlag()
end

function MySpec:onWriteStream(streamId, connection)
    streamWriteInt8(streamId, self.spec_mySpec.value)
end

function MySpec:onReadStream(streamId, connection)
    self.spec_mySpec.value = streamReadInt8(streamId)
end

function MySpec:onWriteUpdateStream(streamId, connection, dirtyMask)
    if streamWriteBool(streamId, bit32.band(dirtyMask, self.spec_mySpec.dirtyFlag) ~= 0) then
        streamWriteInt8(streamId, self.spec_mySpec.value)
    end
end

function MySpec:onReadUpdateStream(streamId, timestamp, connection)
    if streamReadBool(streamId) then
        self.spec_mySpec.value = streamReadInt8(streamId)
    end
end
"""


def test_specializations() -> None:
    print("Specializations")
    check(ids(lua(GOOD_SPEC)) == [], "vanilla-shaped specialization: no findings")

    no_prereq = GOOD_SPEC.replace("MySpec.prerequisitesPresent", "MySpec.somethingElse")
    check("LUA-SPEC-001" in ids(lua(no_prereq)), "no prerequisitesPresent -> LUA-SPEC-001")

    no_register = GOOD_SPEC.replace("MySpec.registerEventListeners", "MySpec.registerStuff")
    check("LUA-SPEC-001" in ids(lua(no_register)), "handlers without registerEventListeners -> LUA-SPEC-001")

    missing_handler = GOOD_SPEC.replace("function MySpec:onLoad(", "function MySpec:onLoadX(")
    check("LUA-SPEC-002" in ids(lua(missing_handler)), "registered handler not defined -> LUA-SPEC-002")

    no_read = GOOD_SPEC.replace("function MySpec:onReadStream(", "function MySpec:onReadStreamX(")
    check("LUA-SPEC-003" in ids(lua(no_read)), "onWriteStream without onReadStream -> LUA-SPEC-003")

    unregistered = GOOD_SPEC.replace(
        '    SpecializationUtil.registerEventListener(vehicleType, "onWriteStream", MySpec)\n', ""
    )
    check("LUA-SPEC-003" in ids(lua(unregistered)), "stream handler not registered -> LUA-SPEC-003")

    mismatch = GOOD_SPEC.replace("self.spec_mySpec.value = streamReadInt8(streamId)\nend\n\nfunction MySpec:onWriteUpdateStream",
                                 "self.spec_mySpec.value = streamReadInt16(streamId)\nend\n\nfunction MySpec:onWriteUpdateStream")
    check("LUA-SPEC-004" in ids(lua(mismatch)), "Int8 written / Int16 read -> LUA-SPEC-004")

    no_dirty = GOOD_SPEC.replace("self.spec_mySpec.dirtyFlag = self:getNextDirtyFlag()", "self.spec_mySpec.dirtyFlag = 1")
    check("LUA-SPEC-005" in ids(lua(no_dirty)), "update stream without dirty flags -> LUA-SPEC-005")

    plain_script = "MyScript = {}\nfunction MyScript:loadMap() end\naddModEventListener(MyScript)\n"
    check(ids(lua(plain_script)) == [], "plain script is not treated as a specialization")


# ----------------------------------------------------------------------
# Outdated API
# ----------------------------------------------------------------------


def test_legacy_api() -> None:
    print("Outdated API")
    cases: list[tuple[str, str]] = [
        ("local p = g_currentMission.player", "LUA-OLD-001"),
        ("local v = g_currentMission.controlledVehicle", "LUA-OLD-002"),
        ("for _, v in pairs(g_currentMission.vehicles) do end", "LUA-OLD-003"),
        ("if g_currentMission.isMultiplayer then end", "LUA-OLD-004"),
        ("local x = vehicle:getIsActiveForSound()", "LUA-OLD-005"),
        ("local x = vehicle:hasInputConflictWithSelection()", "LUA-OLD-006"),
        ("BunkerSilo.onCreate(self, node)", "LUA-OLD-007"),
    ]
    for code, rule in cases:
        check(rule in ids(lua(code)), f"{rule}: {code}")

    check("LUA-OLD-001" not in ids(lua("local p = g_localPlayer")), "g_localPlayer is clean")
    check(ids(lua("local v = g_currentMission.vehicleSystem.vehicles")) == [], "vehicleSystem.vehicles is clean")
    check(
        "LUA-OLD-005" not in ids(lua("function Vehicle:getIsActiveForSound()\nend")),
        "a definition of a deprecated method is not a use",
    )
    check(
        "LUA-OLD-001" not in ids(lua("-- g_currentMission.player\n")),
        "legacy API inside a comment is ignored",
    )

    # Things vanilla still does must NOT be flagged.
    clean = """
        local v = Utils.getNoNil(x, 1)
        local server = g_currentMission:getIsServer()
        local info = g_currentMission.missionInfo
        local f = getXMLString(xmlFile, key)
    """
    check(ids(lua(clean)) == [], "Utils.getNoNil / getIsServer / missionInfo / getXML* outside specs are clean")

    spec_raw = GOOD_SPEC.replace(
        "self.spec_mySpec = {}", "self.spec_mySpec = {}\n    local v = getXMLInt(savegame.xmlFile, 'a')"
    )
    info = [f for f in lua(spec_raw).findings if f.rule_id == "LUA-OLD-008"]
    check(bool(info) and info[0].severity is Severity.INFO, "raw getXML* in a specialization is INFO only")

    deprecated = 'local ok = xmlFile:hasProperty("vehicle.ackermannSteering")'
    check("LUA-OLD-009" in ids(lua(deprecated)), "deprecated XML path -> LUA-OLD-009")
    declared = (
        'XMLUtil.checkDeprecatedXMLElements(self.xmlFile,\n'
        '    "vehicle.ackermannSteering", "vehicle.wheels.ackermannSteeringConfigurations")'
    )
    check("LUA-OLD-009" not in ids(lua(declared)), "checkDeprecatedXMLElements declarations are not uses")
    check(
        "LUA-OLD-009" not in ids(lua('xmlFile:hasProperty("vehicle.motor")')),
        "vehicle.motor (still read by vanilla Motorized) is not flagged",
    )


def test_sandbox() -> None:
    print("Lua sandbox")
    check("LUA-SAN-001" in ids(lua('local t = os.time()')), "os.time() is an error")
    check("LUA-SAN-001" in ids(lua('local d = os.date("*t")')), "os.date() is an error")
    check(lua('local t = os.time()').findings[0].severity is Severity.ERROR, "os.time() severity is ERROR")
    check("LUA-SAN-001" not in ids(lua("-- local t = os.time()\n")), "os.time() inside a comment is ignored")
    check("LUA-SAN-001" not in ids(lua('local s = "os.time()"')), "os.time() inside a string is ignored")
    check("LUA-SAN-002" in ids(lua("table.move(a, 1, #a, 1, b)")), "table.move() is an error")
    check("LUA-SAN-002" not in ids(lua("local packed = table.pack(1, 2)")), "table.pack() is not table.move()")
    check("LUA-SAN-003" in ids(lua("if skip then goto continue end\n::continue::")), "authored goto and label are errors")
    check(ids(lua("if skip then goto l19 end\n::l12::")).count("LUA-SAN-003") == 0, "decompiler goto l<number> is not flagged")
    check("LUA-SAN-001" not in ids(lua("local timestamp = g_currentMission.time")), "g_currentMission.time is clean")


# ----------------------------------------------------------------------
# Vanilla regression
# ----------------------------------------------------------------------


def test_vanilla_sources() -> None:
    print("Vanilla sources")
    if not LUA_SRC.is_dir():
        print("  skip  FS25-lua-scripting-main not found")
        return

    lower = LUA_SRC / "VehicleLowerImplementEvent.lua"
    if lower.is_file():
        found = analyze_lua(lower.read_text(encoding="utf-8", errors="replace"))
        errors = [f for f in found.findings if f.severity is Severity.ERROR]
        check(not errors, f"VehicleLowerImplementEvent.lua: no errors ({[f.rule_id for f in errors]})")
        check("VehicleLowerImplementEvent" in found.event_classes, "VehicleLowerImplementEvent is detected as an event")

    # Rules that compare two present bodies or flag API names were calibrated on
    # the vanilla files: they must stay silent here.
    calibrated = {
        "LUA-EVT-004", "LUA-SPEC-004", "LUA-OLD-001", "LUA-OLD-002", "LUA-OLD-003",
        "LUA-OLD-004", "LUA-OLD-005", "LUA-OLD-006", "LUA-OLD-007", "LUA-OLD-009",
        "LUA-SAN-001", "LUA-SAN-002", "LUA-SAN-003",
    }
    hits: dict[str, list[str]] = {}
    files = sorted(LUA_SRC.rglob("*.lua"))
    for path in files:
        found = analyze_lua(path.read_text(encoding="utf-8", errors="replace"))
        for finding in found.findings:
            if finding.rule_id in calibrated:
                hits.setdefault(finding.rule_id, []).append(f"{path.name}:{finding.line}")
    check(len(files) > 200, f"scanned {len(files)} vanilla Lua files")
    for rule in sorted(calibrated):
        check(rule not in hits, f"{rule} silent on vanilla ({hits.get(rule, [])[:3]})")


# ----------------------------------------------------------------------
# End-to-end with LuaAuditor
# ----------------------------------------------------------------------

MOD_DESC = """<?xml version="1.0" encoding="utf-8" standalone="no" ?>
<modDesc descVersion="92">
    <author>t</author><version>1</version>
    {multiplayer}
    <extraSourceFiles>
{sources}
    </extraSourceFiles>
</modDesc>
"""


def make_mod(
    root: Path,
    files: dict[str, str],
    sources: list[str],
    *,
    multiplayer: bool = True,
) -> Path:
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(content), encoding="utf-8")
    source_xml = "\n".join(f'        <sourceFile filename="{name}" />' for name in sources)
    (root / "modDesc.xml").write_text(
        MOD_DESC.format(
            multiplayer='<multiplayer supported="true" />' if multiplayer else "",
            sources=source_xml,
        ),
        encoding="utf-8",
    )
    return root


def report_ids(report: ValidationReport) -> list[str]:
    return [issue.message.split(":", 1)[0] for issue in report.issues if issue.message.startswith("LUA-")]


def audit(files: dict[str, str], sources: list[str], **kwargs) -> ValidationReport:
    with tempfile.TemporaryDirectory() as tmp:
        return LuaAuditor(make_mod(Path(tmp), files, sources, **kwargs)).audit()


def test_auditor() -> None:
    print("LuaAuditor")

    sender = "function Main:go(o)\n    MyEvent.sendEvent(o, 1)\nend\n"
    report = audit(
        {"scripts/event.lua": GOOD_EVENT, "scripts/main.lua": sender},
        ["scripts/event.lua", "scripts/main.lua"],
    )
    check(report.passed and not report_ids(report), "clean registered event: passed, no findings")

    report = audit({"scripts/event.lua": GOOD_EVENT.replace("streamReadInt32", "streamReadInt8")}, ["scripts/event.lua"])
    check(not report.passed and "LUA-EVT-004" in report_ids(report), "broken event: failed with LUA-EVT-004")
    location = next((i.location for i in report.issues if i.message.startswith("LUA-EVT-004")), "")
    check(str(location).replace("\\", "/").startswith("scripts/event.lua:"), f"location has file:line ({location})")

    # source() following: an event that is only loaded by another script.
    report = audit(
        {
            "scripts/main.lua": 'source(Utils.getFilename("scripts/events/e.lua", g_currentModDirectory))\n',
            "scripts/events/e.lua": GOOD_EVENT.replace("streamReadInt32", "streamReadInt8"),
        },
        ["scripts/main.lua"],
    )
    check("LUA-EVT-004" in report_ids(report), "source() targets are audited")

    report = audit({"scripts/main.lua": 'source("scripts/missing.lua")\n'}, ["scripts/main.lua"])
    check(any("does not exist" in i.message for i in report.issues), "source() of a missing file is reported")

    # Missing multiplayer declaration.
    report = audit({"scripts/event.lua": GOOD_EVENT}, ["scripts/event.lua"], multiplayer=False)
    check("LUA-MP-001" in report_ids(report), "network code without <multiplayer> -> LUA-MP-001")
    report = audit({"scripts/plain.lua": "Plain = {}\n"}, ["scripts/plain.lua"], multiplayer=False)
    check("LUA-MP-001" not in report_ids(report), "plain script without <multiplayer> is fine")

    # Event that is defined but never created outside its own class.
    report = audit({"scripts/event.lua": GOOD_EVENT}, ["scripts/event.lua"])
    check("LUA-EVT-007" in report_ids(report), "event nobody sends -> LUA-EVT-007")
    check(report.passed, "LUA-EVT-007 is informational only")
    report = audit(
        {
            "scripts/event.lua": GOOD_EVENT,
            "scripts/main.lua": "function Main:go(o)\n    MyEvent.sendEvent(o, 1)\nend\n",
        },
        ["scripts/event.lua", "scripts/main.lua"],
    )
    check("LUA-EVT-007" not in report_ids(report), "event sent from another file -> no LUA-EVT-007")

    # Wrong-case path is still analysed (modDesc validator reports the case problem).
    with tempfile.TemporaryDirectory() as tmp:
        mod = make_mod(Path(tmp), {"scripts/event.lua": GOOD_EVENT}, ["Scripts/event.lua"])
        report = LuaAuditor(mod).audit()
        check(any("event.lua" in str(i.location) for i in report.issues), "wrong-case path still audited")

    # Nothing registered.
    with tempfile.TemporaryDirectory() as tmp:
        mod = make_mod(Path(tmp), {}, [])
        report = LuaAuditor(mod).audit()
        check(report.passed, "mod without Lua files passes")
    check(not LuaAuditor(Path("Z:/definitely/not/here")).audit().passed, "missing mod folder fails")

    # Unreadable / non-UTF-8 files must not crash the auditor.
    with tempfile.TemporaryDirectory() as tmp:
        mod = make_mod(Path(tmp), {}, ["scripts/bin.lua"])
        (mod / "scripts").mkdir(exist_ok=True)
        (mod / "scripts" / "bin.lua").write_bytes(b"\xff\xfe\x00 not utf8 \x80\x81")
        try:
            LuaAuditor(mod).audit()
            check(True, "binary garbage in a .lua file does not crash")
        except Exception as exc:  # noqa: BLE001 - the point of the test
            check(False, f"binary garbage crashed the auditor: {exc!r}")


def test_desc_version_range() -> None:
    """mods.lua rejects a descVersion outside 90-111 before scripts load."""
    from app.validators.moddesc_validator import ModDescValidator

    print("descVersion range")

    def report_for(version: str) -> ValidationReport:
        with tempfile.TemporaryDirectory() as tmp:
            mod = Path(tmp)
            (mod / "modDesc.xml").write_text(
                f'<modDesc descVersion="{version}"><author>a</author>'
                f"<version>1.0.0.0</version><iconFilename>icon.png</iconFilename></modDesc>",
                encoding="utf-8",
            )
            (mod / "icon.png").write_bytes(b"x")
            return ModDescValidator(mod).validate()

    low = report_for("83")
    high = report_for("112")
    ok = report_for("92")
    current = report_for("104")
    check(
        any(i.severity == Severity.ERROR and "outside 90-111" in i.message for i in low.issues),
        "descVersion 83 is an error",
    )
    check(
        any(i.severity == Severity.ERROR and "outside 90-111" in i.message for i in high.issues),
        "descVersion 112 is an error",
    )
    check(
        not any("outside 90-111" in i.message for i in ok.issues)
        and any(i.severity == Severity.INFO and "descVersion = 92" in i.message for i in ok.issues),
        "descVersion 92 stays valid",
    )
    check(
        any(i.severity == Severity.INFO and "descVersion = 104" in i.message for i in current.issues),
        "descVersion 104 stays valid",
    )


def test_samples_and_pipeline() -> None:
    print("Samples and pipeline")
    ok = run_xml_validation_suite(ROOT / "samples" / "sample_ok_mod")
    lua_ok = ok.section(SECTION_LUA)
    check(lua_ok is not None and lua_ok.passed and not report_ids(lua_ok), "sample_ok_mod: Lua audit is clean")
    check(ok.passed, "sample_ok_mod: whole suite passes")
    check(len(ok.sections) == 8, "suite has eight sections")

    broken = run_xml_validation_suite(ROOT / "samples" / "sample_broken_mod")
    lua_broken = broken.section(SECTION_LUA)
    found = set(report_ids(lua_broken)) if lua_broken else set()
    expected = {"LUA-EVT-001", "LUA-EVT-004", "LUA-EVT-005", "LUA-OLD-001", "LUA-OLD-002", "LUA-MP-001"}
    check(expected <= found, f"sample_broken_mod: expected rules found (missing: {sorted(expected - found)})")
    check(not broken.passed, "sample_broken_mod: suite fails")

    xml_only = run_xml_validation_suite(ROOT / "samples" / "sample_ok_mod", include_lua=False)
    check(len(xml_only.sections) == 7, "include_lua=False skips the Lua section")

    # CLI exit codes
    import main as cli  # noqa: PLC0415

    check(cli.main(["--validate", str(ROOT / "samples" / "sample_ok_mod")]) == 0, "CLI exit code 0 for sample_ok_mod")
    check(cli.main(["--validate", str(ROOT / "samples" / "sample_broken_mod")]) == 1, "CLI exit code 1 for sample_broken_mod")


def main() -> int:
    tests: list[Callable[[], None]] = [
        test_events,
        test_specializations,
        test_legacy_api,
        test_sandbox,
        test_vanilla_sources,
        test_auditor,
        test_desc_version_range,
        test_samples_and_pipeline,
    ]
    for test in tests:
        test()
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
