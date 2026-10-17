-- Sample script for the Lua auditor (clean example, no findings expected).
-- The event below is loaded the way FS25 mods usually do it: through source().
source(Utils.getFilename("scripts/events/SampleSyncEvent.lua", g_currentModDirectory))

SampleScript = {}

function SampleScript:loadMap()
    print("SampleScript loaded (sample_ok_mod)")
end

-- Sends the event: on a client it goes to the server, on the server to all clients.
function SampleScript:resetAmount(object)
    SampleSyncEvent.sendEvent(object, 0)
end

addModEventListener(SampleScript)
