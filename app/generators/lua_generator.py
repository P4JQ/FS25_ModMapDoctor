"""Lua script generator: complete FS25 templates for specializations, events and placeables.

Three script types are supported:

* ``Custom Specialization Mod`` (target: Vehicle)
* ``Network Event Script`` (targets: Vehicle, Placeable, Game Environment)
* ``Placeable Extension`` (target: Placeable)

Every template is modelled on code that exists in the vanilla FS25 sources
(``Documentation/docs`` and ``Documentation/FS25-lua-scripting-main``):

=====================  =====================================================
Template               Vanilla reference
=====================  =====================================================
Vehicle specialization ``Honk`` (hook layout, ``removeEventListener``),
                       ``VinePrepruner`` (stream + dirty-flag pattern),
                       ``Washable`` / ``Wearable`` (savegame paths)
Network event          ``VehicleLowerImplementEvent`` (object events),
                       ``AnimalNameEvent`` / ``FenceRequestDeleteSegmentEvent``
                       (relay arguments), ``VehicleEnterRequestEvent``
                       (server side ``hasGhostObject`` check)
Placeable extension    ``PlaceableSilo`` (xml paths, load/save, streams),
                       ``PlaceableHusbandryFood`` (update stream)
=====================  =====================================================

Deviations from the request that are worth knowing
--------------------------------------------------
* ``EventRegistry:registerEventId()`` does not exist anywhere in the FS25
  sources or documentation, so it is **not** generated (calling it would stop
  the script with a nil error). Event classes are registered with the
  long-standing ``InitEventClass(Class, "Name")`` call instead, guarded so a
  missing function is reported in the log instead of crashing the mod. The
  reference sources contain no top level statements at all (not even
  ``Class = {}``), so the call cannot be confirmed there; the whole block lives
  in :data:`EVENT_REGISTRATION_BLOCK` and is easy to replace.
* Specializations of mods are registered as ``<modName>.<name>``; their data
  table is therefore read through ``self["spec_" .. SPEC_NAME]`` instead of
  ``self.spec_<name>``.

The generator only builds text. It never touches the file system and never
runs Lua.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ScriptType(str, Enum):
    """What kind of Lua script is generated. The value is the label shown in the GUI."""

    SPECIALIZATION = "Custom Specialization Mod"
    NETWORK_EVENT = "Network Event Script"
    PLACEABLE_EXTENSION = "Placeable Extension"


class TargetObject(str, Enum):
    """The game object the script attaches to. The value is the label shown in the GUI."""

    VEHICLE = "Vehicle"
    PLACEABLE = "Placeable"
    GAME_ENVIRONMENT = "Game Environment"


@dataclass(frozen=True, slots=True)
class ScriptTypeInfo:
    """Static description of one script type."""

    summary: str
    allowed_targets: tuple[TargetObject, ...]
    planned_files: tuple[str, ...]  # what a generation run produces
    reference: str  # where the structure comes from (vanilla evidence)
    name_hint: str  # example shown as placeholder in the Script Name field


SCRIPT_TYPE_INFO: dict[ScriptType, ScriptTypeInfo] = {
    ScriptType.SPECIALIZATION: ScriptTypeInfo(
        summary=(
            "A vehicle specialization with all core hooks: prerequisitesPresent, "
            "initSpecialization, registerFunctions, registerEventListeners, onLoad, "
            "onUpdate and onDelete, plus savegame saving and multiplayer sync "
            "(onWriteStream / onReadStream and update streams with dirty flags)."
        ),
        allowed_targets=(TargetObject.VEHICLE,),
        planned_files=("<Name>.lua", "XML snippets (modDesc.xml and vehicle XML)"),
        reference="vanilla Honk, VinePrepruner, Washable and Wearable",
        name_hint="e.g. MyVehicleSpec",
    ),
    ScriptType.NETWORK_EVENT: ScriptTypeInfo(
        summary=(
            "A multiplayer event class extending Event: emptyNew, new, readStream, "
            "writeStream, run and sendEvent, with commented server-side safety checks "
            "and engine registration at the bottom of the file."
        ),
        allowed_targets=(
            TargetObject.VEHICLE,
            TargetObject.PLACEABLE,
            TargetObject.GAME_ENVIRONMENT,
        ),
        planned_files=("<Name>Event.lua", "XML snippets (modDesc.xml)"),
        reference="vanilla VehicleLowerImplementEvent, AnimalNameEvent and VehicleEnterRequestEvent",
        name_hint="e.g. SetFuelLevel (the Event suffix is added)",
    ),
    ScriptType.PLACEABLE_EXTENSION: ScriptTypeInfo(
        summary=(
            "A placeable specialization with XML paths, onLoad, savegame loading and "
            "saving, join sync and update streams. Use it to extend production points, "
            "silos and other placeables."
        ),
        allowed_targets=(TargetObject.PLACEABLE,),
        planned_files=("<Name>.lua", "XML snippets (modDesc.xml and placeable XML)"),
        reference="vanilla PlaceableSilo, PlaceableProductionPoint and PlaceableHusbandryFood",
        name_hint="e.g. MyPlaceableExtension",
    ),
}

# Dropdown contents, in display order.
SCRIPT_TYPE_OPTIONS: tuple[str, ...] = tuple(item.value for item in ScriptType)
TARGET_OBJECT_OPTIONS: tuple[str, ...] = tuple(item.value for item in TargetObject)


# ----------------------------------------------------------------------
# Request / result
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LuaScriptRequest:
    """Everything the user chose in the Lua Generator tab."""

    script_type: ScriptType
    target: TargetObject
    name: str = ""


@dataclass(frozen=True, slots=True)
class GeneratedLuaScript:
    """Result of a generation run."""

    class_name: str  # Lua class, for example ``MyVehicleSpec`` or ``SetFuelLevelEvent``
    lua_filename: str  # suggested file name of the script
    lua_code: str
    xml_filename: str  # suggested file name of the snippet file
    xml_snippet: str  # modDesc.xml / vehicle XML / placeable XML fragments


# ----------------------------------------------------------------------
# Name handling
# ----------------------------------------------------------------------

MAX_NAME_LENGTH = 48

_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]*")

_LUA_KEYWORDS = frozenset(
    {
        "and", "break", "do", "else", "elseif", "end", "false", "for", "function",
        "if", "in", "local", "nil", "not", "or", "repeat", "return", "then", "true",
        "until", "while", "continue",  # 'continue' is added by the GIANTS Engine
    }
)

# Globals the templates rely on: a script class with one of these names would
# shadow them and break the generated code.
_RESERVED_NAMES = frozenset(
    {
        "Class", "Event", "Logging", "NetworkNode", "NetworkUtil", "Placeable",
        "SpecializationUtil", "Utils", "Vehicle", "XMLValueType", "bit32", "math",
        "string", "table",
    }
)

_EVENT_SUFFIX = "Event"


def name_error(script_type: ScriptType, name: str) -> str | None:
    """None when ``name`` can be used for ``script_type``, otherwise the reason why not."""
    text = name.strip()
    if not text:
        return "Script Name is required."
    if not _IDENTIFIER.fullmatch(text):
        return (
            "Script Name must start with a letter and contain only letters, "
            "digits and underscores."
        )
    if len(text) > MAX_NAME_LENGTH:
        return f"Script Name is too long (maximum {MAX_NAME_LENGTH} characters)."
    class_name = resolve_class_name(script_type, text)
    if class_name in _LUA_KEYWORDS:
        return f"'{class_name}' is a Lua keyword and cannot be used as a name."
    if class_name in _RESERVED_NAMES:
        return f"'{class_name}' is used by the engine and cannot be used as a class name."
    return None


def resolve_class_name(script_type: ScriptType, name: str) -> str:
    """Lua class name: PascalCase, and an ``Event`` suffix for events."""
    text = name.strip()
    class_name = text[:1].upper() + text[1:]
    if script_type is ScriptType.NETWORK_EVENT and not class_name.endswith(_EVENT_SUFFIX):
        class_name += _EVENT_SUFFIX
    return class_name


def resolve_spec_name(class_name: str) -> str:
    """Name used in modDesc.xml and XML keys: the class name with a lower-case first letter."""
    return class_name[:1].lower() + class_name[1:]


# ----------------------------------------------------------------------
# Template engine
# ----------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def _render(template: str, values: dict[str, str]) -> str:
    """Replace ``{{key}}`` placeholders. Raises ``KeyError`` for unknown keys.

    A tiny custom syntax is used on purpose: ``str.format`` would clash with Lua
    table braces and ``string.Template`` with the ``$dataS`` paths in XML.
    """

    def replace(match: re.Match[str]) -> str:
        return values[match.group(1)]

    return _PLACEHOLDER.sub(replace, template).strip("\n") + "\n"


# ----------------------------------------------------------------------
# Template: vehicle specialization
# ----------------------------------------------------------------------

_VEHICLE_SPEC_LUA = r"""
-- {{Class}}.lua
-- Vehicle specialization generated by FS25 Mod & Map Doctor.
--
-- The layout follows vanilla FS25 specializations (Honk, VinePrepruner, Washable):
--   * hooks:     prerequisitesPresent, initSpecialization, registerFunctions,
--                registerEventListeners, onLoad, onUpdate, onDelete
--   * savegame:  values are read in onLoad and written in saveToXMLFile
--   * multiplayer: onWriteStream / onReadStream send the full state to a joining client,
--                onWriteUpdateStream / onReadUpdateStream send later changes
--                (server -> clients) using a dirty flag
--
-- The example state is a counter that the server increases every `interval` milliseconds.
-- Replace it with your own data, keeping the read/write order identical on both sides.
--
-- Register the file in modDesc.xml and add it to a vehicle type (see the XML Snippets tab).

{{Class}} = {}

-- The engine registers specializations of a mod as "<modName>.<name from modDesc.xml>".
-- The vehicle keeps the data table of the specialization under "spec_" .. that name, so
-- it is read through these constants instead of self.spec_{{specName}}.
{{Class}}.SPEC_NAME = g_currentModName .. ".{{specName}}"
{{Class}}.SPEC_TABLE_NAME = "spec_" .. {{Class}}.SPEC_NAME

-- Path of the saved values inside the savegame vehicles.xml.
{{Class}}.SAVEGAME_KEY = "vehicles.vehicle(?)." .. {{Class}}.SPEC_NAME

{{Class}}.DEFAULT_INTERVAL = 1000 -- milliseconds between two counter steps
{{Class}}.MAX_COUNTER = 65535 -- largest value that fits the UInt16 used in the network streams


---Checks if all prerequisite specializations are present on the vehicle type.
-- The vehicle type loader calls this for every specialization of a type; return false to
-- keep the specialization away from types that cannot support it.
-- @param table specializations specializations of the vehicle type
-- @return boolean hasPrerequisite true if all prerequisite specializations are present
function {{Class}}.prerequisitesPresent(specializations)
    -- Example (vanilla Honk): only allow drivable vehicles.
    -- return SpecializationUtil.hasSpecialization(Drivable, specializations)
    return true
end


---Called once while the specializations are initialized.
-- Registers the XML paths of the vehicle XML and of the savegame so they are known to the
-- XML schema (unknown paths are reported as warnings in the log).
function {{Class}}.initSpecialization()
    -- <vehicle><{{specName}} interval="1000" /></vehicle>
    local schema = Vehicle.xmlSchema
    schema:setXMLSpecializationType("{{Class}}")
    schema:register(XMLValueType.INT, "vehicle.{{specName}}#interval", "Time between two counter steps in ms", {{Class}}.DEFAULT_INTERVAL)
    schema:setXMLSpecializationType()

    local schemaSavegame = Vehicle.xmlSchemaSavegame
    schemaSavegame:register(XMLValueType.INT, {{Class}}.SAVEGAME_KEY .. "#counter", "Saved counter value")
end


---Registers the functions this specialization adds to the vehicle.
-- Function names share one namespace with all other specializations, so they carry the class name.
-- @param table vehicleType vehicle type
function {{Class}}.registerFunctions(vehicleType)
    SpecializationUtil.registerFunction(vehicleType, "get{{Class}}Counter", {{Class}}.getCounter)
    SpecializationUtil.registerFunction(vehicleType, "set{{Class}}Counter", {{Class}}.setCounter)
end


---Registers the engine events this specialization listens to.
-- Every handler registered here must exist as {{Class}}:<eventName>(), and every on*Stream
-- handler must be registered, otherwise the engine never calls it.
-- @param table vehicleType vehicle type
function {{Class}}.registerEventListeners(vehicleType)
    SpecializationUtil.registerEventListener(vehicleType, "onLoad", {{Class}})
    SpecializationUtil.registerEventListener(vehicleType, "onDelete", {{Class}})
    SpecializationUtil.registerEventListener(vehicleType, "onUpdate", {{Class}})
    SpecializationUtil.registerEventListener(vehicleType, "onReadStream", {{Class}})
    SpecializationUtil.registerEventListener(vehicleType, "onWriteStream", {{Class}})
    SpecializationUtil.registerEventListener(vehicleType, "onReadUpdateStream", {{Class}})
    SpecializationUtil.registerEventListener(vehicleType, "onWriteUpdateStream", {{Class}})
end


---Called when the vehicle is loaded (server and clients).
-- @param table savegame savegame data, nil when the vehicle is newly bought or spawned
function {{Class}}:onLoad(savegame)
    local spec = self[{{Class}}.SPEC_TABLE_NAME]

    -- Values from the vehicle XML.
    spec.interval = math.max(self.xmlFile:getValue("vehicle.{{specName}}#interval", {{Class}}.DEFAULT_INTERVAL), 1)
    spec.timer = 0
    spec.counter = 0

    -- Values from the savegame (the key matches what saveToXMLFile writes).
    if savegame ~= nil then
        spec.counter = savegame.xmlFile:getValue(savegame.key .. "." .. {{Class}}.SPEC_NAME .. "#counter", spec.counter)
    end

    -- One dirty flag per group of values that is sent in the update stream.
    spec.dirtyFlag = self:getNextDirtyFlag()

    -- The server simulates the counter and clients receive it through the update stream,
    -- so clients do not need onUpdate (same pattern as vanilla Honk).
    if not self.isServer then
        SpecializationUtil.removeEventListener(self, "onUpdate", {{Class}})
    end
end


---Called when the vehicle is deleted. Release everything that was created in onLoad
-- (sounds, effects, nodes ...). This skeleton creates nothing that needs cleaning up.
function {{Class}}:onDelete()
end


---Called every frame while the vehicle is active (only on the server, see onLoad).
-- @param float dt time since the last update in milliseconds
-- @param boolean isActiveForInput true if the local player controls this vehicle
-- @param boolean isActiveForInputIgnoreSelection true if controlled, regardless of selection
-- @param boolean isSelected true if the vehicle is selected
function {{Class}}:onUpdate(dt, isActiveForInput, isActiveForInputIgnoreSelection, isSelected)
    local spec = self[{{Class}}.SPEC_TABLE_NAME]

    spec.timer = spec.timer + dt
    if spec.timer >= spec.interval then
        spec.timer = spec.timer - spec.interval
        self:set{{Class}}Counter((spec.counter + 1) % ({{Class}}.MAX_COUNTER + 1))
    end

    -- onUpdate only runs while the vehicle is active. Call self:raiseActive() here if the
    -- counter has to keep running while nobody drives the vehicle.
end


---Returns the current counter value.
-- @return integer counter
function {{Class}}:getCounter()
    return self[{{Class}}.SPEC_TABLE_NAME].counter
end


---Sets the counter. Server only: clients receive the value through the update stream.
-- To change a value from a client, send a network event to the server instead (the
-- "Network Event Script" template of this tool).
-- @param integer counter new value
function {{Class}}:setCounter(counter)
    if not self.isServer then
        Logging.warning("{{Class}}: the counter can only be set on the server.")
        return
    end

    local spec = self[{{Class}}.SPEC_TABLE_NAME]
    counter = math.clamp(counter, 0, {{Class}}.MAX_COUNTER)

    if counter ~= spec.counter then
        spec.counter = counter
        self:raiseDirtyFlags(spec.dirtyFlag) -- send the new value to all clients
    end
end


---Writes the full state for a client that joins the game (server -> client).
-- The order must match onReadStream exactly.
-- @param integer streamId stream id
-- @param table connection connection of the joining client
function {{Class}}:onWriteStream(streamId, connection)
    local spec = self[{{Class}}.SPEC_TABLE_NAME]

    streamWriteUInt16(streamId, spec.counter)
end


---Reads the full state when joining the game (client side).
-- @param integer streamId stream id
-- @param table connection connection to the server
function {{Class}}:onReadStream(streamId, connection)
    local spec = self[{{Class}}.SPEC_TABLE_NAME]

    spec.counter = streamReadUInt16(streamId)
end


---Writes the values that changed since the last update (server -> clients).
-- @param integer streamId stream id
-- @param table connection connection of the receiving client
-- @param integer dirtyMask flags raised with raiseDirtyFlags
function {{Class}}:onWriteUpdateStream(streamId, connection, dirtyMask)
    if not connection:getIsServer() then -- only the server writes updates
        local spec = self[{{Class}}.SPEC_TABLE_NAME]

        if streamWriteBool(streamId, bit32.band(dirtyMask, spec.dirtyFlag) ~= 0) then
            streamWriteUInt16(streamId, spec.counter)
        end
    end
end


---Reads the values written by onWriteUpdateStream (client side).
-- @param integer streamId stream id
-- @param integer timestamp network timestamp
-- @param table connection connection to the server
function {{Class}}:onReadUpdateStream(streamId, timestamp, connection)
    if connection:getIsServer() then -- only clients read updates
        local spec = self[{{Class}}.SPEC_TABLE_NAME]

        if streamReadBool(streamId) then
            spec.counter = streamReadUInt16(streamId)
        end
    end
end


---Writes the values to the savegame. The key already ends with the specialization name.
-- @param table xmlFile savegame xml file
-- @param string key savegame key of this specialization
-- @param table usedModNames mods that are required by the savegame
function {{Class}}:saveToXMLFile(xmlFile, key, usedModNames)
    local spec = self[{{Class}}.SPEC_TABLE_NAME]

    xmlFile:setValue(key .. "#counter", spec.counter)
end
"""

_VEHICLE_SPEC_XML = r"""
<!-- ===== modDesc.xml ===== -->

<!-- The script synchronizes data, so the mod has to declare multiplayer support. -->
<multiplayer supported="true" />

<!-- Registers the Lua file as a specialization. -->
<specializations>
    <specialization name="{{specName}}" className="{{Class}}" filename="scripts/{{Class}}.lua" />
</specializations>

<!-- Adds the specialization to a vehicle type. Pick the parent from $dataS/vehicleTypes.xml;
     baseFillable is the parent used in the TerraFarm documentation. -->
<vehicleTypes>
    <type name="my{{Class}}Vehicle" parent="baseFillable" className="Vehicle" filename="$dataS/scripts/vehicles/Vehicle.lua">
        <specialization name="{{specName}}" />
    </type>
</vehicleTypes>

<!-- ===== Vehicle XML (the vehicle must use the type above) ===== -->

<vehicle type="my{{Class}}Vehicle">
    <{{specName}} interval="1000" />
</vehicle>
"""


# ----------------------------------------------------------------------
# Template: network event
# ----------------------------------------------------------------------

# Registers the event class with the engine (last statement of every event file).
# See the module docstring for why this is not EventRegistry:registerEventId().
EVENT_REGISTRATION_BLOCK = r"""
-- Engine registration. Keep this at the bottom of the file, after all functions are defined.
-- The engine needs it to create the event on the receiving machine; without it the event
-- never arrives. The check turns a missing function into a log message instead of a crash.
if InitEventClass ~= nil then
    InitEventClass({{Class}}, "{{Class}}")
else
    Logging.error("{{Class}}: InitEventClass is not available, the event cannot be registered and will not work in multiplayer.")
end
"""

_EVENT_HEADER = r"""
-- {{Class}}.lua
-- Multiplayer event generated by FS25 Mod & Map Doctor. Target: {{Target}}.
--
-- How the event travels (same flow as vanilla VehicleLowerImplementEvent):
--   1. The machine that wants the change applies it locally and calls {{Class}}.sendEvent().
--   2. On a client the event goes to the server; on the server (or host) it is broadcast to the clients.
--   3. The receiving side runs readStream() -> run(). The server validates the request, applies it
--      and relays it to the other clients; clients simply apply it.
-- sendEvent() never applies the change on the machine that calls it, so do that before sending.
--
-- Load the file through <extraSourceFiles> in modDesc.xml (see the XML Snippets tab).

{{Class}} = {}
local {{Class}}_mt = Class({{Class}}, Event)

-- Largest value the server accepts from a client. Adjust it to your data.
{{Class}}.MAX_AMOUNT = 1000000


---Creates an empty instance. The engine calls this on the receiving machine and fills the
-- instance with readStream(), so it must not need any arguments.
-- @return table self instance of the event
function {{Class}}.emptyNew()
    local self = Event.new({{Class}}_mt)
    return self
end
"""

_EVENT_OBJECT_BODY = r"""

---Creates a new event.
-- @param table {{obj}} {{obj}} the change belongs to
-- @param integer amount example payload, replace it with your own data
-- @return table instance instance of the event
function {{Class}}.new({{obj}}, amount)
    local self = {{Class}}.emptyNew()
    self.{{obj}} = {{obj}}
    self.amount = amount
    return self
end


---Reads the event from the network. The order must match writeStream exactly.
-- @param integer streamId stream id
-- @param table connection connection the data arrived on
function {{Class}}:readStream(streamId, connection)
    self.{{obj}} = NetworkUtil.readNodeObject(streamId)
    self.amount = streamReadInt32(streamId)
    self:run(connection)
end


---Writes the event to the network. The order must match readStream exactly.
-- @param integer streamId stream id
-- @param table connection connection the data is sent on
function {{Class}}:writeStream(streamId, connection)
    NetworkUtil.writeNodeObject(streamId, self.{{obj}})
    streamWriteInt32(streamId, self.amount)
end


---Runs the event on the receiving machine.
-- connection:getIsServer() is true when the data came FROM the server (we are a client) and
-- false when it came from a client (we are the server).
-- @param table connection connection the event arrived on
function {{Class}}:run(connection)
    -- The {{obj}} can be missing or not yet synchronized on this machine (for example while a
    -- player joins). Ignore the event instead of failing.
    if self.{{obj}} == nil or not self.{{obj}}:getIsSynchronized() then
        return
    end

    if not connection:getIsServer() then
        -- ==================================================================
        -- SERVER SIDE SAFETY CHECKS
        -- A client sent this request. Never trust it: validate everything here, BEFORE the
        -- change is applied or relayed to the other clients. Return to reject the request.
        -- ==================================================================

        -- 1. The client may only act on objects it actually knows (vanilla VehicleEnterRequestEvent).
        if not g_server:hasGhostObject(connection, self.{{obj}}) then
            Logging.warning("{{Class}}: {{obj}} is not synchronized to the sending client, request ignored.")
            return
        end

        -- 2. Validate the payload. Clients can send any value.
        if self.amount < 0 or self.amount > {{Class}}.MAX_AMOUNT then
            Logging.warning("{{Class}}: rejected amount %d from a client.", self.amount)
            return
        end

        -- 3. Permissions and ownership. Uncomment and adapt: pick the permission name that fits
        --    your feature (vanilla AI jobs use "hireAssistant" in exactly this way).
        -- local farmId = self.{{obj}}:getOwnerFarmId()
        -- if not g_currentMission:getHasPlayerPermission("hireAssistant", connection, farmId) then
        --     return
        -- end
    end

    -- Applied on every machine that runs the event: the server and the other clients.
    {{Class}}.apply(self.{{obj}}, self.amount)

    if not connection:getIsServer() then
        -- Relay the validated request to all other clients. The sender (connection) is skipped
        -- because it already applied the change locally before sending.
        g_server:broadcastEvent({{Class}}.new(self.{{obj}}, self.amount), nil, connection, self.{{obj}})
    end
end


---Applies the change on one machine. TODO: replace the body with your game logic.
-- Runs on the server and on every client, so it must not depend on server-only state.
-- @param table {{obj}} {{obj}} the change belongs to
-- @param integer amount payload of the event
function {{Class}}.apply({{obj}}, amount)
    Logging.info("{{Class}} received: amount=%d", amount)
end


---Sends the event. Call this after applying the change locally.
-- Broadcasts to all clients when called on the server (or host), otherwise sends the request
-- to the server.
-- @param table {{obj}} {{obj}} the change belongs to
-- @param integer amount payload of the event
-- @param boolean noEventSend true to skip sending (used when the change itself came from an event)
function {{Class}}.sendEvent({{obj}}, amount, noEventSend)
    if noEventSend == nil or noEventSend == false then
        if g_server ~= nil then
            g_server:broadcastEvent({{Class}}.new({{obj}}, amount), nil, nil, {{obj}})
        else
            g_client:getServerConnection():sendEvent({{Class}}.new({{obj}}, amount))
        end
    end
end
"""

_EVENT_ENVIRONMENT_BODY = r"""

---Creates a new event.
-- @param integer amount example payload, replace it with your own data
-- @return table instance instance of the event
function {{Class}}.new(amount)
    local self = {{Class}}.emptyNew()
    self.amount = amount
    return self
end


---Reads the event from the network. The order must match writeStream exactly.
-- @param integer streamId stream id
-- @param table connection connection the data arrived on
function {{Class}}:readStream(streamId, connection)
    self.amount = streamReadInt32(streamId)
    self:run(connection)
end


---Writes the event to the network. The order must match readStream exactly.
-- @param integer streamId stream id
-- @param table connection connection the data is sent on
function {{Class}}:writeStream(streamId, connection)
    streamWriteInt32(streamId, self.amount)
end


---Runs the event on the receiving machine.
-- connection:getIsServer() is true when the data came FROM the server (we are a client) and
-- false when it came from a client (we are the server).
-- @param table connection connection the event arrived on
function {{Class}}:run(connection)
    if not connection:getIsServer() then
        -- ==================================================================
        -- SERVER SIDE SAFETY CHECKS
        -- A client sent this request. Never trust it: validate everything here, BEFORE the
        -- change is applied or relayed to the other clients. Return to reject the request.
        -- ==================================================================

        -- 1. Validate the payload. Clients can send any value.
        if self.amount < 0 or self.amount > {{Class}}.MAX_AMOUNT then
            Logging.warning("{{Class}}: rejected amount %d from a client.", self.amount)
            return
        end

        -- 2. Permissions. Uncomment and adapt: pick the permission name that fits your feature.
        --    The connection tells you who sent the request.
        -- if not g_currentMission:getHasPlayerPermission("hireAssistant", connection) then
        --     return
        -- end
        -- local userId = g_currentMission.userManager:getUserIdByConnection(connection)
    end

    -- Applied on every machine that runs the event: the server and the other clients.
    {{Class}}.apply(self.amount)

    if not connection:getIsServer() then
        -- Relay the validated request to all other clients. The sender (connection) is skipped
        -- because it already applied the change locally before sending.
        g_server:broadcastEvent({{Class}}.new(self.amount), false, connection)
    end
end


---Applies the change on one machine. TODO: replace the body with your game logic.
-- Runs on the server and on every client, so it must not depend on server-only state.
-- The message center call lets other scripts react, for example with
-- g_messageCenter:subscribe({{Class}}, myCallback, myTarget).
-- @param integer amount payload of the event
function {{Class}}.apply(amount)
    Logging.info("{{Class}} received: amount=%d", amount)
    g_messageCenter:publish({{Class}}, amount)
end


---Sends the event. Call this after applying the change locally.
-- Broadcasts to all clients when called on the server (or host), otherwise sends the request
-- to the server.
-- @param integer amount payload of the event
-- @param boolean noEventSend true to skip sending (used when the change itself came from an event)
function {{Class}}.sendEvent(amount, noEventSend)
    if noEventSend == nil or noEventSend == false then
        if g_server ~= nil then
            g_server:broadcastEvent({{Class}}.new(amount), false)
        else
            g_client:getServerConnection():sendEvent({{Class}}.new(amount))
        end
    end
end
"""

_EVENT_XML = r"""
<!-- ===== modDesc.xml ===== -->

<!-- The event travels over the network, so the mod has to declare multiplayer support. -->
<multiplayer supported="true" />

<!-- Loads the event class. List it before any script that calls {{Class}}.sendEvent(). -->
<extraSourceFiles>
    <sourceFile filename="scripts/{{Class}}.lua" />
</extraSourceFiles>

<!-- Usage (Lua): apply your change locally first, then send it.
       {{Class}}.sendEvent({{sendArgs}})
-->
"""


# ----------------------------------------------------------------------
# Template: placeable extension
# ----------------------------------------------------------------------

_PLACEABLE_LUA = r"""
-- {{Class}}.lua
-- Placeable specialization generated by FS25 Mod & Map Doctor.
--
-- The layout follows vanilla placeable specializations (PlaceableSilo, PlaceableProductionPoint,
-- PlaceableHusbandryFood):
--   * init:      prerequisitesPresent, registerXMLPaths, registerSavegameXMLPaths
--   * load:      onLoad (values from the placeable XML) and loadFromXMLFile (savegame values)
--   * save:      saveToXMLFile
--   * multiplayer: onWriteStream / onReadStream for joining clients, update streams with a
--                dirty flag for later changes
--
-- The example state is an integer level. Replace it with your own data, keeping the read/write
-- order identical on both sides. Other placeable events used by vanilla specializations that you
-- can register in registerEventListeners: onFinalizePlacement, onPostFinalizePlacement, onSell.
--
-- Register the file in modDesc.xml and add it to a placeable type (see the XML Snippets tab).

{{Class}} = {}

-- The engine registers specializations of a mod as "<modName>.<name from modDesc.xml>".
-- The placeable keeps the data table of the specialization under "spec_" .. that name, so it
-- is read through these constants instead of self.spec_{{specName}}.
{{Class}}.SPEC_NAME = g_currentModName .. ".{{specName}}"
{{Class}}.SPEC_TABLE_NAME = "spec_" .. {{Class}}.SPEC_NAME

{{Class}}.DEFAULT_START_LEVEL = 0
{{Class}}.MAX_LEVEL = 65535 -- largest value that fits the UInt16 used in the network streams


---Checks if all prerequisite specializations are present on the placeable type.
-- @param table specializations specializations of the placeable type
-- @return boolean hasPrerequisite true if all prerequisite specializations are present
function {{Class}}.prerequisitesPresent(specializations)
    -- Example: only allow placeables that are silos.
    -- return SpecializationUtil.hasSpecialization(PlaceableSilo, specializations)
    return true
end


---Registers the XML paths of the placeable XML.
-- The engine calls this for every specialization while the placeable schema is built.
-- @param table schema xml schema
-- @param string basePath base path of the placeable xml ("placeable")
function {{Class}}.registerXMLPaths(schema, basePath)
    schema:setXMLSpecializationType("{{Class}}")
    schema:register(XMLValueType.INT, basePath .. ".{{specName}}#startLevel", "Level of a new placeable", {{Class}}.DEFAULT_START_LEVEL)
    schema:setXMLSpecializationType()
end


---Registers the XML paths of the savegame.
-- @param table schema savegame xml schema
-- @param string basePath path of this specialization inside the savegame
function {{Class}}.registerSavegameXMLPaths(schema, basePath)
    schema:setXMLSpecializationType("{{Class}}")
    schema:register(XMLValueType.INT, basePath .. "#level", "Saved level")
    schema:setXMLSpecializationType()
end


---Registers the functions this specialization adds to the placeable.
-- Function names share one namespace with all other specializations, so they carry the class name.
-- @param table placeableType placeable type
function {{Class}}.registerFunctions(placeableType)
    SpecializationUtil.registerFunction(placeableType, "get{{Class}}Level", {{Class}}.getLevel)
    SpecializationUtil.registerFunction(placeableType, "set{{Class}}Level", {{Class}}.setLevel)
end


---Registers the engine events this specialization listens to.
-- Every handler registered here must exist as {{Class}}:<eventName>(), and every on*Stream
-- handler must be registered, otherwise the engine never calls it.
-- @param table placeableType placeable type
function {{Class}}.registerEventListeners(placeableType)
    SpecializationUtil.registerEventListener(placeableType, "onLoad", {{Class}})
    SpecializationUtil.registerEventListener(placeableType, "onDelete", {{Class}})
    SpecializationUtil.registerEventListener(placeableType, "onReadStream", {{Class}})
    SpecializationUtil.registerEventListener(placeableType, "onWriteStream", {{Class}})
    SpecializationUtil.registerEventListener(placeableType, "onReadUpdateStream", {{Class}})
    SpecializationUtil.registerEventListener(placeableType, "onWriteUpdateStream", {{Class}})
end


---Called when the placeable is loaded (server and clients). Reads the placeable XML.
-- Savegame values are applied afterwards by loadFromXMLFile.
-- @param table savegame savegame data, nil for a newly placed placeable
function {{Class}}:onLoad(savegame)
    local spec = self[{{Class}}.SPEC_TABLE_NAME]

    spec.level = math.clamp(self.xmlFile:getValue("placeable.{{specName}}#startLevel", {{Class}}.DEFAULT_START_LEVEL), 0, {{Class}}.MAX_LEVEL)

    -- One dirty flag per group of values that is sent in the update stream.
    spec.dirtyFlag = self:getNextDirtyFlag()
end


---Called when the placeable is deleted or sold. Release everything that was created in onLoad
-- (triggers, activatables, effects ...). This skeleton creates nothing that needs cleaning up.
function {{Class}}:onDelete()
end


---Returns the current level.
-- @return integer level
function {{Class}}:getLevel()
    return self[{{Class}}.SPEC_TABLE_NAME].level
end


---Sets the level. Server only: clients receive the value through the update stream.
-- To change a value from a client, send a network event to the server instead (the
-- "Network Event Script" template of this tool, target Placeable).
-- @param integer level new value
function {{Class}}:setLevel(level)
    if not self.isServer then
        Logging.warning("{{Class}}: the level can only be set on the server.")
        return
    end

    local spec = self[{{Class}}.SPEC_TABLE_NAME]
    level = math.clamp(level, 0, {{Class}}.MAX_LEVEL)

    if level ~= spec.level then
        spec.level = level
        self:raiseDirtyFlags(spec.dirtyFlag) -- send the new value to all clients
    end
end


---Loads the saved values. Called by the placeable while it loads from a savegame.
-- The key already ends with the specialization name.
-- @param table xmlFile savegame xml file
-- @param string key savegame key of this specialization
function {{Class}}:loadFromXMLFile(xmlFile, key)
    local spec = self[{{Class}}.SPEC_TABLE_NAME]

    spec.level = math.clamp(xmlFile:getValue(key .. "#level", spec.level), 0, {{Class}}.MAX_LEVEL)
end


---Writes the values to the savegame. The key already ends with the specialization name.
-- @param table xmlFile savegame xml file
-- @param string key savegame key of this specialization
-- @param table usedModNames mods that are required by the savegame
function {{Class}}:saveToXMLFile(xmlFile, key, usedModNames)
    local spec = self[{{Class}}.SPEC_TABLE_NAME]

    xmlFile:setValue(key .. "#level", spec.level)
end


---Writes the full state for a client that joins the game (server -> client).
-- The order must match onReadStream exactly.
-- @param integer streamId stream id
-- @param table connection connection of the joining client
function {{Class}}:onWriteStream(streamId, connection)
    local spec = self[{{Class}}.SPEC_TABLE_NAME]

    streamWriteUInt16(streamId, spec.level)
end


---Reads the full state when joining the game (client side).
-- @param integer streamId stream id
-- @param table connection connection to the server
function {{Class}}:onReadStream(streamId, connection)
    local spec = self[{{Class}}.SPEC_TABLE_NAME]

    spec.level = streamReadUInt16(streamId)
end


---Writes the values that changed since the last update (server -> clients).
-- @param integer streamId stream id
-- @param table connection connection of the receiving client
-- @param integer dirtyMask flags raised with raiseDirtyFlags
function {{Class}}:onWriteUpdateStream(streamId, connection, dirtyMask)
    if not connection:getIsServer() then -- only the server writes updates
        local spec = self[{{Class}}.SPEC_TABLE_NAME]

        if streamWriteBool(streamId, bit32.band(dirtyMask, spec.dirtyFlag) ~= 0) then
            streamWriteUInt16(streamId, spec.level)
        end
    end
end


---Reads the values written by onWriteUpdateStream (client side).
-- @param integer streamId stream id
-- @param integer timestamp network timestamp
-- @param table connection connection to the server
function {{Class}}:onReadUpdateStream(streamId, timestamp, connection)
    if connection:getIsServer() then -- only clients read updates
        local spec = self[{{Class}}.SPEC_TABLE_NAME]

        if streamReadBool(streamId) then
            spec.level = streamReadUInt16(streamId)
        end
    end
end
"""

_PLACEABLE_XML = r"""
<!-- ===== modDesc.xml ===== -->

<!-- The script synchronizes data, so the mod has to declare multiplayer support. -->
<multiplayer supported="true" />

<!-- Registers the Lua file as a placeable specialization. -->
<specializations>
    <specialization name="{{specName}}" className="{{Class}}" filename="scripts/{{Class}}.lua" />
</specializations>

<!-- Adds the specialization to a placeable type. Replace the parent with a vanilla placeable type
     from $dataS/placeableTypes.xml (for example the type of the silo or production point you
     extend). className and filename are taken from the parent. -->
<placeableTypes>
    <type name="my{{Class}}Placeable" parent="REPLACE_WITH_VANILLA_PLACEABLE_TYPE">
        <specialization name="{{specName}}" />
    </type>
</placeableTypes>

<!-- ===== Placeable XML (the placeable must use the type above) ===== -->

<placeable type="my{{Class}}Placeable">
    <{{specName}} startLevel="0" />
</placeable>
"""


# ----------------------------------------------------------------------
# Generator
# ----------------------------------------------------------------------


class LuaGenerator:
    """Builds Lua scripts from the templates above."""

    @staticmethod
    def parse_script_type(label: str) -> ScriptType:
        """Dropdown label -> ``ScriptType``. Raises ``ValueError`` for unknown labels."""
        try:
            return ScriptType(label)
        except ValueError:
            raise ValueError(f"Unknown script type: {label!r}") from None

    @staticmethod
    def parse_target(label: str) -> TargetObject:
        """Dropdown label -> ``TargetObject``. Raises ``ValueError`` for unknown labels."""
        try:
            return TargetObject(label)
        except ValueError:
            raise ValueError(f"Unknown target object: {label!r}") from None

    @staticmethod
    def info(script_type: ScriptType) -> ScriptTypeInfo:
        return SCRIPT_TYPE_INFO[script_type]

    @classmethod
    def compatibility_error(cls, script_type: ScriptType, target: TargetObject) -> str | None:
        """None when the combination is valid, otherwise a sentence explaining why not."""
        allowed = cls.info(script_type).allowed_targets
        if target in allowed:
            return None
        options = " or ".join(item.value for item in allowed)
        return f'"{script_type.value}" can only target: {options}.'

    @classmethod
    def validate(cls, request: LuaScriptRequest) -> None:
        """Raise ``ValueError`` if the request cannot be generated."""
        problem = cls.compatibility_error(request.script_type, request.target)
        if problem is None:
            problem = name_error(request.script_type, request.name)
        if problem is not None:
            raise ValueError(problem)

    @classmethod
    def generate(cls, request: LuaScriptRequest) -> GeneratedLuaScript:
        """Generate the Lua script and its XML snippets.

        Raises:
            ValueError: unsupported script type / target combination or invalid name.
        """
        cls.validate(request)

        class_name = resolve_class_name(request.script_type, request.name)
        values = {
            "Class": class_name,
            "specName": resolve_spec_name(class_name),
            "Target": request.target.value,
        }

        if request.script_type is ScriptType.SPECIALIZATION:
            lua, xml = _VEHICLE_SPEC_LUA, _VEHICLE_SPEC_XML
        elif request.script_type is ScriptType.PLACEABLE_EXTENSION:
            lua, xml = _PLACEABLE_LUA, _PLACEABLE_XML
        else:
            lua, xml = cls._event_templates(request.target, values)

        return GeneratedLuaScript(
            class_name=class_name,
            lua_filename=f"{class_name}.lua",
            lua_code=_render(lua, values),
            xml_filename=f"{class_name}_snippets.xml",
            xml_snippet=_render(xml, values),
        )

    @staticmethod
    def _event_templates(target: TargetObject, values: dict[str, str]) -> tuple[str, str]:
        """Assemble the event Lua text (header, target specific body, registration) and its XML."""
        if target is TargetObject.GAME_ENVIRONMENT:
            body = _EVENT_ENVIRONMENT_BODY
            values["sendArgs"] = "amount"
        else:
            body = _EVENT_OBJECT_BODY
            obj = "vehicle" if target is TargetObject.VEHICLE else "placeable"
            values["obj"] = obj
            values["sendArgs"] = f"{obj}, amount"
        lua = _EVENT_HEADER + body + "\n\n" + EVENT_REGISTRATION_BLOCK
        return lua, _EVENT_XML
