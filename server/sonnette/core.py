"""Transport-independent, single-process call state machine. No media is stored."""
from dataclasses import dataclass, field
import time
import uuid


class ProtocolError(Exception):
    pass


@dataclass
class Call:
    id: str
    caller: str
    callee: str
    state: str
    deadline: float
    offered: bool = False
    answered: bool = False
    connected: set[str] = field(default_factory=set)

    def peer(self, user: str) -> str:
        return self.callee if user == self.caller else self.caller


class Hub:
    """All mutations must be serialized by the transport adapter."""
    def __init__(self, permissions: dict[str, list[str]], clock=time.monotonic):
        self.permissions = permissions
        self.clock = clock
        self.online: set[str] = set()
        self.calls: dict[str, Call] = {}
        self.busy: dict[str, str] = {}

    def connect(self, user):
        if user in self.online:
            raise ProtocolError('already_connected')
        self.online.add(user)

    def disconnect(self, user):
        self.online.discard(user)
        call = self.calls.get(self.busy.get(user))
        return self.finish(call, 'disconnected') if call else []

    def finish(self, call, reason):
        self.calls.pop(call.id, None)
        self.busy.pop(call.caller, None)
        self.busy.pop(call.callee, None)
        return [(p, {'type': 'call.ended', 'call_id': call.id, 'reason': reason})
                for p in (call.caller, call.callee)]

    def expire(self):
        events = []
        for call in list(self.calls.values()):
            if self.clock() >= call.deadline:
                events.extend(self.finish(call, 'timeout'))
        return events

    def handle(self, user, msg):
        kind = msg.get('type')
        if kind == 'ping':
            return {}, []
        if kind == 'call.invite':
            peer = msg.get('to')
            if not isinstance(peer, str) or peer == user or peer not in self.permissions[user]:
                raise ProtocolError('forbidden')
            if peer not in self.online:
                raise ProtocolError('offline')
            if user in self.busy or peer in self.busy:
                raise ProtocolError('busy')
            cid = str(uuid.uuid4())
            call = Call(cid, user, peer, 'ringing', self.clock() + 30)
            self.calls[cid] = call
            self.busy[user] = self.busy[peer] = cid
            return {'call_id': cid}, [
                (user, {'type': 'call.ringing', 'call_id': cid, 'peer': peer}),
                (peer, {'type': 'call.incoming', 'call_id': cid, 'peer': user})]
        cid = msg.get('call_id')
        if not isinstance(cid, str):
            raise ProtocolError('invalid_call_id')
        call = self.calls.get(cid)
        if call is None or user not in (call.caller, call.callee):
            raise ProtocolError('unknown_call')
        if kind == 'call.end':
            return {}, self.finish(call, 'hangup')
        if kind == 'call.reject':
            if user != call.callee or call.state != 'ringing':
                raise ProtocolError('invalid_state')
            return {}, self.finish(call, 'rejected')
        if kind == 'call.accept':
            if user != call.callee or call.state != 'ringing':
                raise ProtocolError('invalid_state')
            call.state, call.deadline = 'connecting', self.clock() + 45
            return {}, [(p, {'type': 'call.accepted', 'call_id': cid,
                             'offerer': call.caller}) for p in (call.callee, call.caller)]
        if kind in ('rtc.offer', 'rtc.answer'):
            sdp = msg.get('sdp')
            if not isinstance(sdp, str) or not 1 <= len(sdp) <= 60000:
                raise ProtocolError('invalid_sdp')
            if call.state != 'connecting':
                raise ProtocolError('invalid_state')
            if kind == 'rtc.offer':
                if user != call.caller or call.offered:
                    raise ProtocolError('invalid_state')
                call.offered = True
            else:
                if user != call.callee or not call.offered or call.answered:
                    raise ProtocolError('invalid_state')
                call.answered = True
            return {}, [(call.peer(user), {'type': kind, 'call_id': cid, 'sdp': sdp})]
        if kind == 'rtc.ice':
            candidate = msg.get('candidate')
            if call.state not in ('connecting', 'active'):
                raise ProtocolError('invalid_state')
            if not isinstance(candidate, dict):
                raise ProtocolError('invalid_candidate')
            value, mid, index = (candidate.get(k) for k in ('candidate', 'sdpMid', 'sdpMLineIndex'))
            if not isinstance(value, str) or len(value) > 4096:
                raise ProtocolError('invalid_candidate')
            if mid is not None and (not isinstance(mid, str) or len(mid) > 128):
                raise ProtocolError('invalid_candidate')
            if index is not None and (type(index) is not int or not 0 <= index <= 64):
                raise ProtocolError('invalid_candidate')
            return {}, [(call.peer(user), {'type': kind, 'call_id': cid,
                         'candidate': {'candidate': value, 'sdpMid': mid, 'sdpMLineIndex': index}})]
        if kind == 'media.ready':
            if call.state not in ('connecting', 'active') or not call.answered:
                raise ProtocolError('invalid_state')
            call.connected.add(user)
            if len(call.connected) == 2 and call.state != 'active':
                call.state, call.deadline = 'active', self.clock() + 3600
                return {}, [(p, {'type': 'call.active', 'call_id': cid})
                            for p in (call.caller, call.callee)]
            return {}, []
        raise ProtocolError('unknown_message')
