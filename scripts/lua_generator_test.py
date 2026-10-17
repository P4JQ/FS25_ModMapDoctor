"""Tests for the Lua generator templates (no GUI needed).

Run from the project root:

    python scripts/lua_generator_test.py

Layers of checking:

1. Model: options, compatibility table, name rules, file names, ASCII-only English output.
2. Static: the Lua auditor must find nothing in any generated script, and the generated XML
   snippets must be well-formed and must pass the mod auditor together with the script.
3. Dynamic (needs ``pip install lupa``, skipped otherwise): every script is loaded into a real
   Lua VM against a small mock of the engine and exercised end to end: client -> server -> client
   event flow, server-side rejection of bad requests, stream round-trips with type checking,
   dirty flags, savegame save/load and the registration hooks.

The mock engine is intentionally tiny: it proves that the generated code is syntactically valid,
internally consistent and follows the call protocol of the vanilla scripts. It cannot prove that
the real engine accepts every call; see the notes in ``lua_generator.py``.
"""

from __future__ import annotations

import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.models import Severity  # noqa: E402
from app.generators import (  # noqa: E402
    SCRIPT_TYPE_OPTIONS,
    TARGET_OBJECT_OPTIONS,
    GeneratedLuaScript,
    LuaGenerator,
    LuaScriptRequest,
    ScriptType,
    TargetObject,
    name_error,
)
from app.generators.lua_generator import (  # noqa: E402
    MAX_NAME_LENGTH,
    resolve_class_name,
    resolve_spec_name,
)
from app.validators.lua_auditor import LuaAuditor, analyze_lua  # noqa: E402

try:
    from lupa import LuaError, LuaRuntime
except ImportError:  # pragma: no cover - optional dev dependency
    LuaRuntime = None  # type: ignore[assignment,misc]
    LuaError = Exception  # type: ignore[assignment,misc]

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


# (script type, target, name typed by the user)
VARIANTS: list[tuple[ScriptType, TargetObject, str]] = [
    (ScriptType.SPECIALIZATION, TargetObject.VEHICLE, "MyVehicleSpec"),
    (ScriptType.NETWORK_EVENT, TargetObject.VEHICLE, "SetFuelLevel"),
    (ScriptType.NETWORK_EVENT, TargetObject.PLACEABLE, "SetSiloLevelEvent"),
    (ScriptType.NETWORK_EVENT, TargetObject.GAME_ENVIRONMENT, "GlobalPing"),
    (ScriptType.PLACEABLE_EXTENSION, TargetObject.PLACEABLE, "MyPlaceableExtension"),
]


def generate(script_type: ScriptType, target: TargetObject, name: str) -> GeneratedLuaScript:
    return LuaGenerator.generate(LuaScriptRequest(script_type, target, name))


# ----------------------------------------------------------------------
# 1. Model
# ----------------------------------------------------------------------


def test_model() -> None:
    print("Model")
    check(
        SCRIPT_TYPE_OPTIONS
        == ("Custom Specialization Mod", "Network Event Script", "Placeable Extension"),
        "script type labels",
    )
    check(TARGET_OBJECT_OPTIONS == ("Vehicle", "Placeable", "Game Environment"), "target labels")

    ok = LuaGenerator.compatibility_error
    check(ok(ScriptType.SPECIALIZATION, TargetObject.VEHICLE) is None, "specialization + vehicle")
    check(ok(ScriptType.SPECIALIZATION, TargetObject.PLACEABLE) is not None, "specialization + placeable rejected")
    check(ok(ScriptType.SPECIALIZATION, TargetObject.GAME_ENVIRONMENT) is not None, "specialization + environment rejected")
    for target in TargetObject:
        check(ok(ScriptType.NETWORK_EVENT, target) is None, f"event + {target.value}")
    check(ok(ScriptType.PLACEABLE_EXTENSION, TargetObject.PLACEABLE) is None, "placeable extension + placeable")
    check(ok(ScriptType.PLACEABLE_EXTENSION, TargetObject.VEHICLE) is not None, "placeable extension + vehicle rejected")

    # Names
    check(name_error(ScriptType.SPECIALIZATION, "") == "Script Name is required.", "empty name rejected")
    check(name_error(ScriptType.SPECIALIZATION, "   ") is not None, "blank name rejected")
    for bad in ("1Spec", "My Spec", "My-Spec", "Spec!", "Sp\u00e4c", "_Spec"):
        check(name_error(ScriptType.SPECIALIZATION, bad) is not None, f"invalid name rejected: {bad!r}")
    check(name_error(ScriptType.SPECIALIZATION, "A" * (MAX_NAME_LENGTH + 1)) is not None, "overlong name rejected")
    check(name_error(ScriptType.SPECIALIZATION, "A" * MAX_NAME_LENGTH) is None, "longest allowed name accepted")
    for reserved in ("Vehicle", "Placeable", "Event", "Logging", "Class", "NetworkUtil"):
        check(name_error(ScriptType.SPECIALIZATION, reserved) is not None, f"reserved name rejected: {reserved}")
    check(name_error(ScriptType.NETWORK_EVENT, "Event") is not None, "event named 'Event' rejected")
    check(name_error(ScriptType.SPECIALIZATION, "end") is None, "'end' becomes 'End' and is a valid class name")
    check(name_error(ScriptType.SPECIALIZATION, "MyVehicleSpec") is None, "normal name accepted")
    check(name_error(ScriptType.SPECIALIZATION, "  Padded  ") is None, "surrounding spaces are ignored")

    # Name resolution
    check(resolve_class_name(ScriptType.NETWORK_EVENT, "setFuel") == "SetFuelEvent", "event suffix added")
    check(resolve_class_name(ScriptType.NETWORK_EVENT, "SetFuelEvent") == "SetFuelEvent", "event suffix not doubled")
    check(resolve_class_name(ScriptType.SPECIALIZATION, "mySpec") == "MySpec", "class name is PascalCase")
    check(resolve_spec_name("MySpec") == "mySpec", "spec name is lowerCamelCase")

    # Validation errors surface from generate()
    for request in (
        LuaScriptRequest(ScriptType.PLACEABLE_EXTENSION, TargetObject.VEHICLE, "Foo"),
        LuaScriptRequest(ScriptType.SPECIALIZATION, TargetObject.VEHICLE, ""),
        LuaScriptRequest(ScriptType.SPECIALIZATION, TargetObject.VEHICLE, "Vehicle"),
    ):
        try:
            LuaGenerator.generate(request)
        except ValueError:
            check(True, f"generate() rejects {request.script_type.value} / {request.target.value} / {request.name!r}")
        else:
            check(False, f"generate() rejects {request.script_type.value} / {request.target.value} / {request.name!r}")


def test_output_shape() -> None:
    print("Output shape")
    for script_type, target, name in VARIANTS:
        label = f"{script_type.value} / {target.value}"
        result = generate(script_type, target, name)
        check(result.lua_filename == f"{result.class_name}.lua", f"{label}: file name")
        check(result.xml_filename == f"{result.class_name}_snippets.xml", f"{label}: snippet file name")
        for kind, text in (("lua", result.lua_code), ("xml", result.xml_snippet)):
            check("{{" not in text and "}}" not in text, f"{label}: {kind} has no unresolved placeholders")
            check(text.endswith("\n") and not text.endswith("\n\n"), f"{label}: {kind} ends with one newline")
            check("\r" not in text and "\t" not in text, f"{label}: {kind} uses LF and spaces only")
            check(text.isascii(), f"{label}: {kind} is plain ASCII (English only)")
            check(all(len(line) == len(line.rstrip()) for line in text.split("\n")), f"{label}: {kind} has no trailing spaces")
        check(result.lua_code.count(result.class_name) >= 10, f"{label}: class name is used throughout")

    # Event specific layout required by the engine.
    for target in TargetObject:
        code = generate(ScriptType.NETWORK_EVENT, target, "Probe").lua_code
        # "function " prefixes skip the header comment, which mentions sendEvent() as well.
        positions = [code.find(marker) for marker in (
            "function ProbeEvent.emptyNew(", "function ProbeEvent.new(", "function ProbeEvent:readStream(",
            "function ProbeEvent:writeStream(", "function ProbeEvent:run(", "function ProbeEvent.sendEvent(",
            "InitEventClass(ProbeEvent",
        )]
        check(all(p >= 0 for p in positions), f"event/{target.value}: all required functions present")
        check(positions == sorted(positions), f"event/{target.value}: required order, registration last")
        check("EventRegistry" not in code, f"event/{target.value}: does not use the non-existent EventRegistry")
        check("SERVER SIDE SAFETY CHECKS" in code, f"event/{target.value}: explains server-side checks")
        check(code.rstrip().endswith("end"), f"event/{target.value}: registration block is the last statement")

    # Specialization hooks required by the request.
    code = generate(ScriptType.SPECIALIZATION, TargetObject.VEHICLE, "Probe").lua_code
    for hook in (
        "Probe.prerequisitesPresent(", "Probe.initSpecialization(", "Probe.registerEventListeners(",
        "Probe:onLoad(", "Probe:onUpdate(", "Probe:onWriteStream(", "Probe:onReadStream(",
    ):
        check(hook in code, f"vehicle specialization: {hook}")

    code = generate(ScriptType.PLACEABLE_EXTENSION, TargetObject.PLACEABLE, "Probe").lua_code
    for hook in (
        "Probe.prerequisitesPresent(", "Probe.registerXMLPaths(", "Probe.registerSavegameXMLPaths(",
        "Probe:onLoad(", "Probe:loadFromXMLFile(", "Probe:saveToXMLFile(",
    ):
        check(hook in code, f"placeable extension: {hook}")


# ----------------------------------------------------------------------
# 2. Static
# ----------------------------------------------------------------------


def wrap_snippet(snippet: str) -> str:
    return f'<modDesc descVersion="92">\n{snippet}\n</modDesc>\n'


def test_static() -> None:
    print("Static checks")
    for script_type, target, name in VARIANTS:
        label = f"{script_type.value} / {target.value}"
        result = generate(script_type, target, name)

        findings = analyze_lua(result.lua_code).findings
        check(not findings, f"{label}: Lua auditor finds nothing ({[f.rule_id for f in findings]})")

        try:
            ET.fromstring(wrap_snippet(result.xml_snippet))
            check(True, f"{label}: XML snippet is well-formed")
        except ET.ParseError as exc:
            check(False, f"{label}: XML snippet is well-formed ({exc})")

        # The generated script + registration must pass the mod auditor as a whole.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "scripts" / result.lua_filename).write_text(result.lua_code, encoding="utf-8")
            (root / "modDesc.xml").write_text(wrap_snippet(result.xml_snippet), encoding="utf-8")
            report = LuaAuditor(root).audit()
            bad = [
                issue.message[:60]
                for issue in report.issues
                if issue.severity in (Severity.ERROR, Severity.WARNING)
            ]
            check(report.passed and not bad, f"{label}: mod auditor passes with the snippet ({bad})")
            audited = any(result.lua_filename in str(issue.location) or result.lua_filename in issue.message for issue in report.issues)
            check(audited, f"{label}: the snippet registers the script so the auditor finds it")

    # Without the multiplayer declaration the auditor must complain (proves the snippet matters).
    result = generate(ScriptType.NETWORK_EVENT, TargetObject.VEHICLE, "Probe")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "scripts").mkdir()
        (root / "scripts" / result.lua_filename).write_text(result.lua_code, encoding="utf-8")
        snippet = result.xml_snippet.replace('<multiplayer supported="true" />', "")
        (root / "modDesc.xml").write_text(wrap_snippet(snippet), encoding="utf-8")
        messages = " ".join(issue.message for issue in LuaAuditor(root).audit().issues)
        check("LUA-MP-001" in messages, "removing <multiplayer> from the snippet is detected")


# ----------------------------------------------------------------------
# 3. Dynamic (real Lua VM + mock engine)
# ----------------------------------------------------------------------

HARNESS = r"""
-- ===== mock of the parts of the engine the templates touch =====
local STREAM_TYPES = {"Int8", "UInt8", "Int16", "UInt16", "Int32", "UInt32", "Bool", "String", "Float32"}

function newStream()
    return {items = {}, pos = 1}
end

for _, typeName in ipairs(STREAM_TYPES) do
    _G["streamWrite" .. typeName] = function(stream, value)
        assert(value ~= nil, "streamWrite" .. typeName .. " called with nil")
        stream.items[#stream.items + 1] = {typeName, value}
        return value -- the real streamWriteBool returns the value as well
    end
    _G["streamRead" .. typeName] = function(stream)
        local item = stream.items[stream.pos]
        assert(item ~= nil, "stream underflow: read " .. typeName .. " but nothing was written")
        assert(item[1] == typeName, "stream mismatch: wrote " .. item[1] .. " but read " .. typeName)
        stream.pos = stream.pos + 1
        return item[2]
    end
end

function assertConsumed(stream, what)
    assert(stream.pos == #stream.items + 1, what .. ": not every written value was read")
end

bit32 = {band = function(a, b) return a & b end}
math.clamp = function(value, low, high) return math.max(low, math.min(high, value)) end

Logging = {log = {}}
local function logger(level)
    return function(format, ...)
        Logging.log[#Logging.log + 1] = {level, string.format(format, ...)}
    end
end
Logging.info, Logging.warning, Logging.error = logger("info"), logger("warning"), logger("error")

function countLog(level, needle)
    local count = 0
    for _, entry in ipairs(Logging.log) do
        if entry[1] == level and (needle == nil or entry[2]:find(needle, 1, true)) then
            count = count + 1
        end
    end
    return count
end

Event = {}
function Event.new(metatable) return setmetatable({}, metatable) end
function Class(class, parent)
    if parent ~= nil then setmetatable(class, {__index = parent}) end
    return {__index = class}
end

NetworkUtil = {objects = {}}
function NetworkUtil.writeNodeObject(stream, object)
    stream.items[#stream.items + 1] = {"NodeObject", object and object.id or 0}
end
function NetworkUtil.readNodeObject(stream)
    local item = stream.items[stream.pos]
    assert(item ~= nil, "stream underflow: read NodeObject but nothing was written")
    assert(item[1] == "NodeObject", "stream mismatch: wrote " .. item[1] .. " but read NodeObject")
    stream.pos = stream.pos + 1
    return NetworkUtil.objects[item[2]]
end

function newConnection(isServer)
    return {getIsServer = function(self) return isServer end}
end

Net = {toServer = {}, broadcasts = {}, ghost = true}
g_server = {
    broadcastEvent = function(self, event, sendLocal, ignoreConnection, object)
        Net.broadcasts[#Net.broadcasts + 1] = {event = event, sendLocal = sendLocal, ignore = ignoreConnection, object = object}
    end,
    hasGhostObject = function(self, connection, object) return Net.ghost end,
}
g_client = {
    getServerConnection = function()
        return {sendEvent = function(self, event) Net.toServer[#Net.toServer + 1] = event end}
    end,
}
g_messageCenter = {
    published = {},
    publish = function(self, messageType, ...) self.published[#self.published + 1] = {messageType, ...} end,
}

-- Serializes an event like the network layer does and runs readStream() on the receiver.
function deliver(event, EventClass, connection)
    local stream = newStream()
    event:writeStream(stream, connection)
    local received = EventClass.emptyNew()
    received:readStream(stream, connection)
    assertConsumed(stream, "event")
    return received
end

function callAsClient(fn, ...)
    local savedServer = g_server
    g_server = nil
    local ok, err = pcall(fn, ...)
    g_server = savedServer
    assert(ok, err)
end

-- XML schema mock
function newSchema()
    local schema = {paths = {}}
    function schema:register(valueType, path, description, default) self.paths[path] = {valueType, default} end
    function schema:setXMLSpecializationType(name) end
    return schema
end
XMLValueType = {INT = "INT", FLOAT = "FLOAT", BOOL = "BOOL", STRING = "STRING"}

-- type / specialization mock
SpecializationUtil = {}
function SpecializationUtil.hasSpecialization(spec, specializations) return false end
function SpecializationUtil.registerFunction(typeDef, name, func) typeDef.functions[name] = func end
function SpecializationUtil.registerEventListener(typeDef, name, class) typeDef.listeners[name] = class end
function SpecializationUtil.removeEventListener(object, name, class) object.removed[name] = true end

function newTypeDef() return {functions = {}, listeners = {}} end

function assertListenersExist(typeDef)
    for name, class in pairs(typeDef.listeners) do
        assert(type(class[name]) == "function", "registered handler " .. name .. " is not defined")
    end
end

function newXmlFile(values)
    values = values or {}
    return {
        values = values,
        getValue = function(self, path, default)
            local value = self.values[path]
            if value == nil then return default end
            return value
        end,
        setValue = function(self, path, value) self.values[path] = value end,
    }
end

function newObject(typeDef, isServer, xmlValues)
    local object = {isServer = isServer, isClient = true, removed = {}, dirty = {}, xmlFile = newXmlFile(xmlValues)}
    object.getNextDirtyFlag = function() return 1 end
    object.raiseDirtyFlags = function(self, flags) self.dirty[#self.dirty + 1] = flags end
    for name, func in pairs(typeDef.functions) do object[name] = func end
    return object
end

g_currentModName = "FS25_Test"
"""

# --- event scenarios -----------------------------------------------------------------------

EVENT_OBJECT_SCENARIO = r"""
local E = _G[CLASS]
local registered = {}
local vehicle = {id = 7, getIsSynchronized = function() return true end, getOwnerFarmId = function() return 1 end}
NetworkUtil.objects[7] = vehicle
local fromClient, fromServer = newConnection(false), newConnection(true)

-- 1) a client sends a request: it travels to the server, which validates, applies and relays it
callAsClient(E.sendEvent, vehicle, 42)
assert(#Net.toServer == 1, "client sendEvent must send exactly one event to the server")
local request = table.remove(Net.toServer)
local atServer = deliver(request, E, fromClient)
assert(atServer.amount == 42, "amount must survive the stream round trip")
assert(atServer.OBJ == vehicle, "object must survive the stream round trip")
assert(countLog("info", "amount=42") == 1, "the server must apply the change once")
assert(#Net.broadcasts == 1, "the server must relay the request to the other clients")
assert(Net.broadcasts[1].ignore == fromClient, "the relay must skip the sending client")
assert(Net.broadcasts[1].object == vehicle, "the relay must pass the object for ghost handling")

-- 2) the relayed event arrives at another client: apply only, never relay again
deliver(Net.broadcasts[1].event, E, fromServer)
assert(countLog("info", "amount=42") == 2, "the other client must apply the change")
assert(#Net.broadcasts == 1, "clients must never relay")

-- 3) bad payloads are rejected by the server before anything is applied or relayed
Logging.log = {}
deliver(E.new(vehicle, -5), E, fromClient)
deliver(E.new(vehicle, E.MAX_AMOUNT + 1), E, fromClient)
assert(countLog("warning", "rejected amount") == 2, "both bad amounts must be rejected with a warning")
assert(countLog("info") == 0 and #Net.broadcasts == 1, "rejected requests must not be applied or relayed")

-- 4) clients that do not know the object are rejected
Net.ghost = false
deliver(E.new(vehicle, 5), E, fromClient)
assert(countLog("warning", "not synchronized") == 1 and #Net.broadcasts == 1, "ghost check must reject")
Net.ghost = true

-- 5) missing / unsynchronized objects are ignored, not fatal
Logging.log = {}
deliver(E.new(nil, 5), E, fromClient)
vehicle.getIsSynchronized = function() return false end
deliver(E.new(vehicle, 5), E, fromClient)
vehicle.getIsSynchronized = function() return true end
assert(countLog("info") == 0 and #Net.broadcasts == 1, "unsynchronized objects must be ignored")

-- 6) the server broadcasts directly; noEventSend suppresses the event
E.sendEvent(vehicle, 1)
assert(#Net.broadcasts == 2 and Net.broadcasts[2].ignore == nil, "server sendEvent must broadcast to everyone")
E.sendEvent(vehicle, 1, true)
callAsClient(E.sendEvent, vehicle, 1, true)
assert(#Net.broadcasts == 2 and #Net.toServer == 0, "noEventSend must send nothing")

-- 7) registration
InitEventClass = function(class, name) registered[name] = class end
"""

EVENT_ENVIRONMENT_SCENARIO = r"""
local E = _G[CLASS]
local fromClient, fromServer = newConnection(false), newConnection(true)

callAsClient(E.sendEvent, 42)
assert(#Net.toServer == 1, "client sendEvent must send exactly one event to the server")
local atServer = deliver(table.remove(Net.toServer), E, fromClient)
assert(atServer.amount == 42, "amount must survive the stream round trip")
assert(countLog("info", "amount=42") == 1, "the server must apply the change once")
assert(#Net.broadcasts == 1, "the server must relay the request to the other clients")
assert(Net.broadcasts[1].ignore == fromClient and Net.broadcasts[1].sendLocal == false,
    "the relay must skip the sender and must not send locally")
assert(#g_messageCenter.published == 1 and g_messageCenter.published[1][1] == E
    and g_messageCenter.published[1][2] == 42, "the change must be published on the message center")

deliver(Net.broadcasts[1].event, E, fromServer)
assert(countLog("info", "amount=42") == 2 and #Net.broadcasts == 1, "clients apply but never relay")

Logging.log = {}
deliver(E.new(-1), E, fromClient)
deliver(E.new(E.MAX_AMOUNT + 1), E, fromClient)
assert(countLog("warning", "rejected amount") == 2, "bad amounts must be rejected")
assert(countLog("info") == 0 and #Net.broadcasts == 1, "rejected requests must not be applied or relayed")

E.sendEvent(5)
assert(#Net.broadcasts == 2 and Net.broadcasts[2].sendLocal == false, "server sendEvent broadcasts without local send")
E.sendEvent(5, true)
callAsClient(E.sendEvent, 5, true)
assert(#Net.broadcasts == 2 and #Net.toServer == 0, "noEventSend must send nothing")
"""

EVENT_REGISTRATION_SCENARIO = r"""
-- loaded with InitEventClass available: the class must be registered under its own name
assert(registeredEvents[CLASS] == _G[CLASS], "InitEventClass must be called with the class and its name")
"""

# --- specialization scenarios ---------------------------------------------------------------

VEHICLE_SCENARIO = r"""
local C = _G[CLASS]
assert(C.prerequisitesPresent({}) == true, "prerequisitesPresent must accept a plain type")
assert(C.SPEC_NAME == "FS25_Test." .. SPEC, "spec name must be <modName>.<name>")

Vehicle = {xmlSchema = newSchema(), xmlSchemaSavegame = newSchema()}
C.initSpecialization()
assert(Vehicle.xmlSchema.paths["vehicle." .. SPEC .. "#interval"] ~= nil, "interval XML path must be registered")
local savePath = "vehicles.vehicle(?).FS25_Test." .. SPEC .. "#counter"
assert(Vehicle.xmlSchemaSavegame.paths[savePath] ~= nil, "savegame path must be registered")

local typeDef = newTypeDef()
C.registerFunctions(typeDef)
C.registerEventListeners(typeDef)
assertListenersExist(typeDef)
for _, name in ipairs({"onLoad", "onUpdate", "onDelete", "onReadStream", "onWriteStream", "onReadUpdateStream", "onWriteUpdateStream"}) do
    assert(typeDef.listeners[name] == C, name .. " must be registered")
end
local getter, setter = "get" .. CLASS .. "Counter", "set" .. CLASS .. "Counter"
assert(typeDef.functions[getter] and typeDef.functions[setter], "getter and setter must be registered")

local function create(isServer, xmlValues, savegame)
    local vehicle = newObject(typeDef, isServer, xmlValues)
    vehicle[C.SPEC_TABLE_NAME] = {}
    C.onLoad(vehicle, savegame)
    return vehicle
end

local server = create(true, {["vehicle." .. SPEC .. "#interval"] = 1000})
local client = create(false)
assert(client.removed.onUpdate == true and server.removed.onUpdate == nil,
    "only clients drop the onUpdate listener")
assert(server[getter](server) == 0, "counter starts at 0")

-- the server simulates, every change raises the dirty flag
for _ = 1, 5 do C.onUpdate(server, 600, true, true, true) end
local counter = server[getter](server)
assert(counter == 3, "5 x 600 ms with a 1000 ms interval must give 3 steps, got " .. counter)
assert(#server.dirty == 3 and server.dirty[1] == server[C.SPEC_TABLE_NAME].dirtyFlag, "each step raises the dirty flag")

-- join sync
local join = newStream()
C.onWriteStream(server, join, newConnection(false))
C.onReadStream(client, join, newConnection(true))
assertConsumed(join, "onWriteStream/onReadStream")
assert(client[getter](client) == 3, "client must receive the counter when joining")

-- update stream: dirty value is sent, clean value is not
server[setter](server, 9)
local update = newStream()
C.onWriteUpdateStream(server, update, newConnection(false), server[C.SPEC_TABLE_NAME].dirtyFlag)
C.onReadUpdateStream(client, update, 0, newConnection(true))
assertConsumed(update, "update stream (dirty)")
assert(client[getter](client) == 9, "client must receive the changed counter")

server[setter](server, 20)
local clean = newStream()
C.onWriteUpdateStream(server, clean, newConnection(false), 0)
C.onReadUpdateStream(client, clean, 0, newConnection(true))
assertConsumed(clean, "update stream (clean)")
assert(client[getter](client) == 9, "a clean update must not change the client")

-- direction guards: the wrong side neither writes nor reads
local wrongWrite, wrongRead = newStream(), newStream()
C.onWriteUpdateStream(client, wrongWrite, newConnection(true), 1)
assert(#wrongWrite.items == 0, "a client must not write update streams")
wrongRead.items[1] = {"Bool", true}
C.onReadUpdateStream(server, wrongRead, 0, newConnection(false))
assert(wrongRead.pos == 1, "the server must not read update streams")

-- clients cannot change the counter
Logging.log = {}
client[setter](client, 77)
assert(client[getter](client) == 9 and countLog("warning", "only be set on the server") == 1, "client setter must refuse")

-- limits
server[setter](server, 1000000)
assert(server[getter](server) == C.MAX_COUNTER, "counter is clamped to the UInt16 range")
C.onUpdate(server, 1000, true, true, true)
assert(server[getter](server) == 0, "counter wraps around after the maximum")

-- savegame round trip (key layout of Vehicle:saveToXMLFile / savegame.key .. "." .. name)
server[setter](server, 123)
local saveXml = newXmlFile()
local name = C.SPEC_NAME
C.saveToXMLFile(server, saveXml, "vehicles.vehicle(0)." .. name, {})
assert(saveXml.values["vehicles.vehicle(0)." .. name .. "#counter"] == 123, "counter must be saved under key#counter")
local restored = create(true, nil, {key = "vehicles.vehicle(0)", xmlFile = saveXml})
assert(restored[getter](restored) == 123, "counter must be restored from the savegame")
assert(create(true, nil, nil)[getter](create(true)) == 0, "no savegame -> default")
"""

PLACEABLE_SCENARIO = r"""
local C = _G[CLASS]
assert(C.prerequisitesPresent({}) == true, "prerequisitesPresent must accept a plain type")
assert(C.SPEC_NAME == "FS25_Test." .. SPEC, "spec name must be <modName>.<name>")

local schema, saveSchema = newSchema(), newSchema()
C.registerXMLPaths(schema, "placeable")
assert(schema.paths["placeable." .. SPEC .. "#startLevel"] ~= nil, "startLevel XML path must be registered")
C.registerSavegameXMLPaths(saveSchema, "placeables.placeable(?).FS25_Test." .. SPEC)
assert(saveSchema.paths["placeables.placeable(?).FS25_Test." .. SPEC .. "#level"] ~= nil, "level savegame path must be registered")

local typeDef = newTypeDef()
C.registerFunctions(typeDef)
C.registerEventListeners(typeDef)
assertListenersExist(typeDef)
for _, name in ipairs({"onLoad", "onDelete", "onReadStream", "onWriteStream", "onReadUpdateStream", "onWriteUpdateStream"}) do
    assert(typeDef.listeners[name] == C, name .. " must be registered")
end
local getter, setter = "get" .. CLASS .. "Level", "set" .. CLASS .. "Level"
assert(typeDef.functions[getter] and typeDef.functions[setter], "getter and setter must be registered")

local function create(isServer, xmlValues)
    local placeable = newObject(typeDef, isServer, xmlValues)
    placeable[C.SPEC_TABLE_NAME] = {}
    C.onLoad(placeable, nil)
    return placeable
end

local server = create(true, {["placeable." .. SPEC .. "#startLevel"] = 5})
local client = create(false)
assert(server[getter](server) == 5, "onLoad must read startLevel from the placeable XML")
assert(client[getter](client) == 0, "default start level is used when the XML has no value")

-- savegame: loadFromXMLFile applies saved values on top of the XML defaults
server[setter](server, 30)
local saveXml = newXmlFile()
local key = "placeables.placeable(0)." .. C.SPEC_NAME
C.saveToXMLFile(server, saveXml, key, {})
assert(saveXml.values[key .. "#level"] == 30, "level must be saved under key#level")
local restored = create(true, {["placeable." .. SPEC .. "#startLevel"] = 5})
C.loadFromXMLFile(restored, saveXml, key)
assert(restored[getter](restored) == 30, "level must be restored from the savegame")
C.loadFromXMLFile(restored, newXmlFile(), key)
assert(restored[getter](restored) == 30, "missing savegame value keeps the current level")

-- join sync and update streams
local join = newStream()
C.onWriteStream(server, join, newConnection(false))
C.onReadStream(client, join, newConnection(true))
assertConsumed(join, "onWriteStream/onReadStream")
assert(client[getter](client) == 30, "client must receive the level when joining")

server.dirty = {}
server[setter](server, 44)
assert(#server.dirty == 1, "a change raises the dirty flag once; no change raises nothing")
server[setter](server, 44)
assert(#server.dirty == 1, "setting the same level again must not raise the dirty flag")
local update = newStream()
C.onWriteUpdateStream(server, update, newConnection(false), server[C.SPEC_TABLE_NAME].dirtyFlag)
C.onReadUpdateStream(client, update, 0, newConnection(true))
assertConsumed(update, "update stream")
assert(client[getter](client) == 44, "client must receive the changed level")

Logging.log = {}
client[setter](client, 1)
assert(client[getter](client) == 44 and countLog("warning", "only be set on the server") == 1, "client setter must refuse")
server[setter](server, -10)
assert(server[getter](server) == 0, "level is clamped at 0")
"""


def new_runtime() -> "LuaRuntime":
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HARNESS)
    return lua


def execute_scenario(code: str, scenario: str, result: GeneratedLuaScript) -> str | None:
    """Load the generated script and run a scenario. Returns the assertion text on failure."""
    spec = result.class_name[:1].lower() + result.class_name[1:]
    try:
        lua = new_runtime()
        lua.execute("registeredEvents = {}")
        lua.execute("InitEventClass = function(class, name) registeredEvents[name] = class end")
        lua.execute(code)
        lua.execute(f'CLASS = "{result.class_name}"; SPEC = "{spec}"\n' + scenario)
    except LuaError as exc:
        return str(exc).splitlines()[0][:230]
    return None


def run_lua(label: str, code: str, scenario: str, result: GeneratedLuaScript) -> None:
    """Run a scenario and record the outcome as one check."""
    error = execute_scenario(code, scenario, result)
    check(error is None, label if error is None else f"{label}: {error}")


def test_dynamic() -> None:
    print("Lua VM with mock engine")
    if LuaRuntime is None:
        print("  skip  lupa is not installed (pip install lupa)")
        return

    for script_type, target, name in VARIANTS:
        label = f"{script_type.value} / {target.value}"
        result = generate(script_type, target, name)

        # Syntax: every file must at least load without running anything dangerous.
        try:
            new_runtime().execute(f"assert(load([==[{result.lua_code}]==]))")
            check(True, f"{label}: valid Lua syntax")
        except LuaError as exc:
            check(False, f"{label}: valid Lua syntax ({exc})")
            continue

        if script_type is ScriptType.SPECIALIZATION:
            run_lua(f"{label}: hooks, streams, dirty flags, savegame", result.lua_code, VEHICLE_SCENARIO, result)
        elif script_type is ScriptType.PLACEABLE_EXTENSION:
            run_lua(f"{label}: xml paths, load/save, streams", result.lua_code, PLACEABLE_SCENARIO, result)
        else:
            scenario = EVENT_ENVIRONMENT_SCENARIO if target is TargetObject.GAME_ENVIRONMENT else EVENT_OBJECT_SCENARIO
            obj = "vehicle" if target is TargetObject.VEHICLE else "placeable"
            scenario = scenario.replace("OBJ", obj)
            run_lua(f"{label}: client -> server -> client flow", result.lua_code, scenario, result)
            run_lua(f"{label}: registration call", result.lua_code, EVENT_REGISTRATION_SCENARIO, result)

            # Without InitEventClass the file must still load and report the problem.
            try:
                lua = new_runtime()
                lua.execute("InitEventClass = nil")
                lua.execute(result.lua_code)
                lua.execute(f'assert(countLog("error", "InitEventClass is not available") == 1)')
                check(True, f"{label}: missing InitEventClass is logged, not fatal")
            except LuaError as exc:
                check(False, f"{label}: missing InitEventClass is logged, not fatal ({exc})")

    # A mutated template must be caught by the mock (proves the scenarios can fail).
    result = generate(ScriptType.NETWORK_EVENT, TargetObject.VEHICLE, "Probe")
    broken = result.lua_code.replace("self.amount = streamReadInt32(streamId)", "self.amount = streamReadInt8(streamId)")
    error = execute_scenario(broken, EVENT_OBJECT_SCENARIO.replace("OBJ", "vehicle"), result)
    check(error is not None and "stream mismatch" in error, "mock detects a read/write type mismatch in a mutated event")
    broken = result.lua_code.replace("g_server:broadcastEvent(ProbeEvent.new(self.vehicle, self.amount), nil, connection, self.vehicle)", "-- relay removed")
    error = execute_scenario(broken, EVENT_OBJECT_SCENARIO.replace("OBJ", "vehicle"), result)
    check(error is not None and "relay" in error, "mock detects a missing relay in a mutated event")
    broken = result.lua_code.replace("if self.amount < 0 or self.amount > ProbeEvent.MAX_AMOUNT then", "if false then")
    error = execute_scenario(broken, EVENT_OBJECT_SCENARIO.replace("OBJ", "vehicle"), result)
    check(error is not None and "rejected" in error, "mock detects a removed server-side validation")


def main() -> int:
    tests: list[Callable[[], None]] = [test_model, test_output_shape, test_static, test_dynamic]
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
