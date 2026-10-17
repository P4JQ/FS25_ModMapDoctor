-- Clean multiplayer event following the vanilla FS25 template
-- (see VehicleLowerImplementEvent.lua): emptyNew / new / readStream /
-- writeStream / run / sendEvent, with matching read and write order.

SampleSyncEvent = {}
local SampleSyncEvent_mt = Class(SampleSyncEvent, Event)

function SampleSyncEvent.emptyNew()
    return Event.new(SampleSyncEvent_mt)
end

function SampleSyncEvent.new(object, amount)
    local self = SampleSyncEvent.emptyNew()

    self.object = object
    self.amount = amount

    return self
end

function SampleSyncEvent:readStream(streamId, connection)
    self.object = NetworkUtil.readNodeObject(streamId)
    self.amount = streamReadInt32(streamId)

    self:run(connection)
end

function SampleSyncEvent:writeStream(streamId, connection)
    NetworkUtil.writeNodeObject(streamId, self.object)
    streamWriteInt32(streamId, self.amount)
end

function SampleSyncEvent:run(connection)
    -- A client request is applied on the server and relayed to every client.
    if not connection:getIsServer() then
        g_server:broadcastEvent(SampleSyncEvent.new(self.object, self.amount), nil, connection, self.object)
    end
end

function SampleSyncEvent.sendEvent(object, amount, noEventSend)
    if noEventSend == nil or noEventSend == false then
        if g_server ~= nil then
            g_server:broadcastEvent(SampleSyncEvent.new(object, amount), nil, nil, object)
        else
            g_client:getServerConnection():sendEvent(SampleSyncEvent.new(object, amount))
        end
    end
end
