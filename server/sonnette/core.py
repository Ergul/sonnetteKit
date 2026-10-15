"""Transport-independent, single-process call state machine. No media is stored."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
import uuid


class ProtocolError(Exception):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Call:
    id: str
    caller: str
    caller_principal: str
    callee_principal: str
    callees: set[str]
    state: str
    deadline: float
    requested_at: str = field(default_factory=utc_now)
    answered_at: str | None = None
    accepted_by: str | None = None
    offered: bool = False
    answered: bool = False
    connected: set[str] = field(default_factory=set)

    @property
    def callee(self):
        """Compatibility accessor for the selected or sole callee session."""
        if self.accepted_by is not None:
            return self.accepted_by
        return next(iter(self.callees)) if len(self.callees) == 1 else None

    def signaling_participants(self):
        if self.accepted_by is not None:
            return (self.caller, self.accepted_by)
        return (self.caller, *sorted(self.callees))

    def peer(self, user: str) -> str:
        if user == self.caller:
            if self.accepted_by is None:
                raise ProtocolError('invalid_state')
            return self.accepted_by
        if user == self.accepted_by:
            return self.caller
        raise ProtocolError('unknown_call')


class Hub:
    """All mutations must be serialized by the transport adapter."""
    def __init__(self, permissions: dict[str, list[str]], clock=time.monotonic):
        self.permissions = {key: list(value) for key, value in permissions.items()}
        self.clock = clock
        self.online: set[str] = set()
        self.calls: dict[str, Call] = {}
        self.busy: dict[str, str] = {}
        self.session_principal: dict[str, str] = {}
        self.principal_sessions: dict[str, set[str]] = {}
        self.principal_metadata: dict[str, dict[str, str]] = {}
        self.ring_timeout: dict[str, int] = {}

    def connect(self, user, *, principal=None, allow=None, metadata=None,
                ring_timeout=30):
        if user in self.online:
            raise ProtocolError('already_connected')
        principal = principal or user
        self.online.add(user)
        self.session_principal[user] = principal
        self.principal_sessions.setdefault(principal, set()).add(user)
        if allow is not None:
            self.permissions[principal] = list(allow)
        else:
            self.permissions.setdefault(principal, [])
        if metadata:
            self.principal_metadata[principal] = dict(metadata)
        self.ring_timeout[principal] = max(10, min(120, int(ring_timeout)))

    def disconnect(self, user):
        self.online.discard(user)
        principal = self.session_principal.pop(user, None)
        if principal is None:
            return []
        sessions = self.principal_sessions.get(principal)
        sessions.discard(user)
        if not sessions:
            self.principal_sessions.pop(principal, None)

        call = self.calls.get(self.busy.get(principal))
        if call is None:
            return []
        if user == call.caller or user == call.accepted_by:
            return self.finish(call, 'disconnected')
        if call.state == 'ringing' and user in call.callees:
            call.callees.discard(user)
            if not call.callees:
                return self.finish(call, 'disconnected')
        return []

    def _peer_details(self, principal):
        metadata = self.principal_metadata.get(principal, {})
        return {
            'peer': principal,
            'peer_label': metadata.get('label', principal),
            'peer_location': metadata.get('location', ''),
        }

    def finish(self, call, reason):
        self.calls.pop(call.id, None)
        self.busy.pop(call.caller_principal, None)
        self.busy.pop(call.callee_principal, None)
        payload = {
            'type': 'call.ended',
            'call_id': call.id,
            'reason': reason,
            'caller_principal': call.caller_principal,
            'callee_principal': call.callee_principal,
            'requested_at': call.requested_at,
            'answered_at': call.answered_at or '',
            'ended_at': utc_now(),
        }
        return [(participant, dict(payload))
                for participant in dict.fromkeys(call.signaling_participants())]

    def expire(self):
        events = []
        for call in list(self.calls.values()):
            if self.clock() >= call.deadline:
                events.extend(self.finish(call, 'timeout'))
        return events

    def handle(self, user, msg):
        kind = msg.get('type')
        principal = self.session_principal.get(user)
        if principal is None:
            raise ProtocolError('offline')
        if kind == 'ping':
            return {}, []
        if kind == 'call.invite':
            peer_principal = msg.get('to')
            if (not isinstance(peer_principal, str)
                    or peer_principal == principal
                    or peer_principal not in self.permissions.get(principal, [])):
                raise ProtocolError('forbidden')
            peer_sessions = set(self.principal_sessions.get(peer_principal, set()))
            if not peer_sessions:
                raise ProtocolError('offline')
            if principal in self.busy or peer_principal in self.busy:
                raise ProtocolError('busy')
            cid = str(uuid.uuid4())
            call = Call(
                id=cid,
                caller=user,
                caller_principal=principal,
                callee_principal=peer_principal,
                callees=peer_sessions,
                state='ringing',
                deadline=self.clock() + self.ring_timeout.get(principal, 30),
            )
            self.calls[cid] = call
            self.busy[principal] = self.busy[peer_principal] = cid
            return {'call_id': cid}, [
                (user, {'type': 'call.ringing', 'call_id': cid,
                        **self._peer_details(peer_principal)}),
                *((peer, {'type': 'call.incoming', 'call_id': cid,
                          **self._peer_details(principal)})
                  for peer in sorted(peer_sessions)),
            ]
        cid = msg.get('call_id')
        if not isinstance(cid, str):
            raise ProtocolError('invalid_call_id')
        call = self.calls.get(cid)
        allowed_sessions = {call.caller, *call.callees} if call else set()
        if call is None or user not in allowed_sessions:
            raise ProtocolError('unknown_call')
        if kind == 'call.end':
            return {}, self.finish(call, 'hangup')
        if kind == 'call.reject':
            if user not in call.callees or call.state != 'ringing':
                raise ProtocolError('invalid_state')
            return {}, self.finish(call, 'rejected')
        if kind == 'call.accept':
            if user not in call.callees or call.state != 'ringing':
                raise ProtocolError('invalid_state')
            other_sessions = call.callees - {user}
            call.accepted_by = user
            call.callees = {user}
            call.state = 'connecting'
            call.answered_at = utc_now()
            call.deadline = self.clock() + 45
            events = [(peer, {'type': 'call.ended', 'call_id': cid,
                              'reason': 'taken'})
                      for peer in sorted(other_sessions)]
            events.extend((participant, {
                'type': 'call.accepted',
                'call_id': cid,
                'offerer': call.caller,
            }) for participant in (user, call.caller))
            return {}, events
        if kind in ('rtc.offer', 'rtc.answer'):
            sdp = msg.get('sdp')
            if not isinstance(sdp, str) or not 1 <= len(sdp) <= 60000:
                raise ProtocolError('invalid_sdp')
            if call.state != 'connecting' or call.accepted_by is None:
                raise ProtocolError('invalid_state')
            if kind == 'rtc.offer':
                if user != call.caller or call.offered:
                    raise ProtocolError('invalid_state')
                call.offered = True
            else:
                if user != call.accepted_by or not call.offered or call.answered:
                    raise ProtocolError('invalid_state')
                call.answered = True
            return {}, [(call.peer(user), {'type': kind, 'call_id': cid, 'sdp': sdp})]
        if kind == 'rtc.ice':
            candidate = msg.get('candidate')
            if call.state not in ('connecting', 'active') or call.accepted_by is None:
                raise ProtocolError('invalid_state')
            if user not in (call.caller, call.accepted_by):
                raise ProtocolError('unknown_call')
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
            if (call.state not in ('connecting', 'active') or not call.answered
                    or user not in (call.caller, call.accepted_by)):
                raise ProtocolError('invalid_state')
            call.connected.add(user)
            if len(call.connected) == 2 and call.state != 'active':
                call.state, call.deadline = 'active', self.clock() + 3600
                return {}, [(participant, {'type': 'call.active',
                                            'call_id': cid})
                            for participant in (call.caller, call.accepted_by)]
            return {}, []
        raise ProtocolError('unknown_message')
