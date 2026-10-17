-- Exists, but broken modDesc points at Scripts/ (wrong case) and a missing file.
-- The Lua auditor still analyzes it and follows the source() call below.
source(Utils.getFilename("scripts/BrokenSyncEvent.lua", g_currentModDirectory))

BrokenSample = {}

function BrokenSample:update(dt)
    -- Legacy API: replaced by g_localPlayer in FS25.
    local player = g_currentMission.player
    local vehicle = g_currentMission.controlledVehicle

    if vehicle ~= nil and player ~= nil then
        BrokenSyncEvent.sendEvent(vehicle, 1)
    end
end

addModEventListener(BrokenSample)
