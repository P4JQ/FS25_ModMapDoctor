-- Deliberately broken multiplayer event (used to demonstrate the Lua auditor):
--   * no emptyNew()           -> the engine cannot create the event on the receiver
--   * writeStream / readStream disagree on type and order -> desync
--   * run() never relays the client request to the other clients

BrokenSyncEvent = {}
local BrokenSyncEvent_mt = Class(BrokenSyncEvent, Event)

function BrokenSyncEvent.new(object, amount)
    local self = Event.new(BrokenSyncEvent_mt)

    self.object = object
    self.amount = amount

    return self
end

function BrokenSyncEvent:readStream(streamId, connection)
    self.amount = streamReadInt32(streamId)
    self.object = NetworkUtil.readNodeObject(streamId)

    self:run(connection)
end

function BrokenSyncEvent:writeStream(streamId, connection)
    NetworkUtil.writeNodeObject(streamId, self.object)
    streamWriteInt32(streamId, self.amount)
end

function BrokenSyncEvent:run(connection)
    if self.object ~= nil then
        self.object:setAmount(self.amount)
    end
end

function BrokenSyncEvent.sendEvent(object, amount, noEventSend)
    if noEventSend == nil or noEventSend == false then
        if g_server ~= nil then
            g_server:broadcastEvent(BrokenSyncEvent.new(object, amount), nil, nil, object)
        else
            g_client:getServerConnection():sendEvent(BrokenSyncEvent.new(object, amount))
        end
    end
end
