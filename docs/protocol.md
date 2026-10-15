# Signaling protocol v1

Transport: JSON text messages over WebSocket `/ws`. Production clients use WSS. Maximum incoming frame size is 65,536 characters (Uvicorn additionally limits WebSocket message bytes). Authenticate within 10 seconds.

Each production connection first obtains a short-lived session from the
trusted application backend. That backend calls:

```text
POST /internal/sessions
X-Internal-API-Key: <server-only key>
Content-Type: application/x-www-form-urlencoded

role=terminal&principalId=door-1&targetId=operator-1&displayName=Entree&location=Accueil&ringTimeoutSeconds=20
```

The JSON response contains `connectionId`, `accessToken`, `signalingUrl`,
`principalId`, `targetId` and `expiresAt`. Terminal sessions live 15 minutes;
operator sessions live 8 hours. The internal key must never be exposed to a
client. `GET /internal/calls/{callId}` returns the authoritative audit state to
the same trusted backend.

First client WebSocket frame:

```json
{"v":1,"type":"auth","device_id":"terminal-RANDOM_CONNECTION_ID","token":"SHORT_LIVED_ACCESS_TOKEN"}
```

The server replies with `ready`, the device ID, its authorized destinations (`peers`) and an `rtc` configuration containing `iceServers` and `iceTransportPolicy`. Credentials are never included in the URL. Invalid authentication closes the connection with code 1008.

After authentication every client message has `v:1` and a unique string `id` (1–100 characters). The server replies with `ack` or `error` carrying the same `id`. The last 256 replies are cached per connection: repeating an ID replays the reply without applying the action again. Replays across a new session are not supported.

| Client message | Fields | Behavior |
| --- | --- | --- |
| `ping` | — | Heartbeat acknowledgment |
| `call.invite` | `to` | Authorize destination, reserve both devices, assign server call ID |
| `call.accept` | `call_id` | Callee only, while ringing |
| `call.reject` | `call_id` | Callee only, while ringing |
| `call.end` | `call_id` | Either participant; also cancels an outgoing invitation |
| `rtc.offer` | `call_id`, `sdp` | Caller only, exactly once after acceptance |
| `rtc.answer` | `call_id`, `sdp` | Callee only, after offer, exactly once |
| `rtc.ice` | `call_id`, `candidate` | Candidate object: `candidate`, `sdpMid`, `sdpMLineIndex` |
| `media.ready` | `call_id` | Participant reports connected media after SDP negotiation |

The server derives the sender from authentication. Clients cannot choose a sender identity or send media signaling to arbitrary peers. SDP is forwarded only to the other participant; it is not interpreted or logged by the application.

Server events: `call.ringing`, `call.incoming`, `rtc.config`, `call.accepted`, `rtc.offer`, `rtc.answer`, `rtc.ice`, `call.active`, `call.ended`.

After acceptance, fresh `rtc.config` is delivered to both participants before `call.accepted`. Only the `offerer` named in `call.accepted` creates the offer. Each client queues ICE until it has set the remote description. Once both participants report media readiness, the server emits `call.active`.

State transitions: idle → ringing → connecting → active → ended.
Reject/cancel/disconnect/timeout can end a call early. Ringing expires after the
trusted backend's configured 10–120 second timeout, connecting after 45 seconds,
and active after 3,600 seconds. Cleanup frees both logical identities. A late
accept or stale call ID returns `unknown_call`.

`to` identifies a logical principal, not a browser tab. An invitation is sent
to every current session for that principal. The first session accepting the
call receives it; the others receive `call.ended` with reason `taken`.

Expected errors include `forbidden`, `offline`, `busy`, `already_connected`, `unknown_call`, `invalid_state`, `invalid_sdp`, `invalid_candidate`, `unknown_message`, `invalid_envelope`.

Clients send a heartbeat every 25 seconds; the server disconnects after 75 seconds without a frame. A per-connection limit of 100 messages/second is enforced. These bounds are initial safeguards, not a complete Internet-facing abuse-prevention system. Unauthenticated connection limiting should be implemented at the infrastructure edge with an accurate client-IP strategy.
