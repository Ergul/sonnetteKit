"""Run exactly one Uvicorn worker: call state and sockets live in this process."""
import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import hmac
import json
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse
from .core import Hub, ProtocolError
from .security import (
    authenticate,
    authenticate_session,
    ice_config,
    issue_session,
    load_devices,
)


def create_app(devices=None, turn_urls=None, secret=None, policy=None, db_path=None,
               origins=None, internal_key=None, public_signaling_url=None):
    @asynccontextmanager
    async def lifespan(app):
        devices_file = os.getenv('DEVICES_FILE', '')
        if devices is not None:
            app.state.devices = devices
        elif devices_file:
            app.state.devices = load_devices(devices_file)
        else:
            app.state.devices = {}
        app.state.urls = turn_urls if turn_urls is not None else [u for u in os.getenv('TURN_URLS', '').split(',') if u]
        app.state.secret = secret if secret is not None else Path(os.environ['TURN_SECRET_FILE']).read_text().strip() if os.getenv('TURN_SECRET_FILE') else ''
        app.state.policy = policy or os.getenv('ICE_POLICY', 'all')
        ice_config('startup', app.state.urls, app.state.secret, app.state.policy)
        app.state.origins = origins if origins is not None else os.getenv('ALLOWED_ORIGINS', '').split(',')
        app.state.hub = Hub({u: d['allow'] for u, d in app.state.devices.items()})
        app.state.sockets = {}
        app.state.sessions = {}
        app.state.internal_key = (internal_key if internal_key is not None
                                  else os.getenv('INTERNAL_API_KEY', '')).strip()
        app.state.public_signaling_url = (
            public_signaling_url if public_signaling_url is not None
            else os.getenv('PUBLIC_SIGNALING_URL', '')).strip()
        if not app.state.devices and not app.state.internal_key:
            raise RuntimeError('INTERNAL_API_KEY is required without static devices')
        if app.state.internal_key and len(app.state.internal_key) < 32:
            raise RuntimeError('INTERNAL_API_KEY must contain at least 32 characters')
        if app.state.internal_key and not app.state.public_signaling_url:
            raise RuntimeError('PUBLIC_SIGNALING_URL is required for dynamic sessions')
        app.state.lock = asyncio.Lock()
        path = db_path or os.getenv('DATABASE_PATH', '/data/calls.sqlite3')
        app.state.db = sqlite3.connect(path, check_same_thread=False)
        app.state.db.execute('CREATE TABLE IF NOT EXISTS endings (call_id TEXT PRIMARY KEY, ended_at INTEGER, reason TEXT)')
        app.state.db.execute('''CREATE TABLE IF NOT EXISTS calls (
            call_id TEXT PRIMARY KEY,
            caller_principal TEXT NOT NULL,
            callee_principal TEXT NOT NULL,
            status TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            answered_at TEXT NOT NULL DEFAULT '',
            ended_at TEXT NOT NULL DEFAULT '',
            duration_seconds INTEGER NOT NULL DEFAULT 0,
            reason TEXT NOT NULL DEFAULT ''
        )''')
        app.state.db.commit()
        async def sweep():
            while True:
                await asyncio.sleep(1)
                async with app.state.lock:
                    await deliver(app.state.hub.expire())
        task = asyncio.create_task(sweep())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        for ws in list(app.state.sockets.values()):
            with suppress(Exception):
                await ws.close(code=1012)
        app.state.db.close()

    app = FastAPI(title='sonnetteKit', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def internal_authorized(request):
        supplied = request.headers.get('x-internal-api-key', '')
        expected = app.state.internal_key
        return bool(expected and supplied and hmac.compare_digest(expected, supplied))

    def internal_response(request, payload, status=200):
        if 'text/plain' in request.headers.get('accept', ''):
            body = ''.join(f'{key}={value}\n' for key, value in payload.items())
            return PlainTextResponse(body, status_code=status)
        return JSONResponse(payload, status_code=status)

    def final_status(reason):
        return {
            'rejected': 'rejected',
            'timeout': 'timeout',
            'hangup': 'ended',
            'disconnected': 'failed',
        }.get(reason, 'ended')

    def remember_started_call(call):
        app.state.db.execute('''
            INSERT INTO calls
                (call_id, caller_principal, callee_principal, status,
                 requested_at)
            VALUES (?, ?, ?, 'ringing', ?)
            ON CONFLICT(call_id) DO NOTHING
        ''', (call.id, call.caller_principal, call.callee_principal,
              call.requested_at))
        app.state.db.commit()

    def remember_answered_call(call):
        app.state.db.execute('''
            UPDATE calls SET status = 'accepted', answered_at = ?
            WHERE call_id = ?
        ''', (call.answered_at or '', call.id))
        app.state.db.commit()

    def remember_active_call(call_id):
        app.state.db.execute(
            "UPDATE calls SET status = 'active' WHERE call_id = ?", (call_id,))
        app.state.db.commit()

    def remember_ended_call(event):
        answered_at = event.get('answered_at', '')
        ended_at = event.get('ended_at', '')
        duration = 0
        if answered_at and ended_at:
            try:
                duration = max(0, round((
                    datetime.fromisoformat(ended_at)
                    - datetime.fromisoformat(answered_at)
                ).total_seconds()))
            except ValueError:
                duration = 0
        app.state.db.execute('''
            INSERT INTO calls
                (call_id, caller_principal, callee_principal, status,
                 requested_at, answered_at, ended_at, duration_seconds, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(call_id) DO UPDATE SET
                status = excluded.status,
                answered_at = excluded.answered_at,
                ended_at = excluded.ended_at,
                duration_seconds = excluded.duration_seconds,
                reason = excluded.reason
        ''', (
            event['call_id'],
            event.get('caller_principal', ''),
            event.get('callee_principal', ''),
            final_status(event['reason']),
            event.get('requested_at', ''),
            answered_at,
            ended_at,
            duration,
            event['reason'],
        ))
        app.state.db.commit()

    async def send(ws, payload):
        await asyncio.wait_for(ws.send_json({'v': 1, **payload}), timeout=3)

    async def deliver(events):
        # Called under lock. Bounded sends prevent a slow peer blocking indefinitely.
        for user, event in events:
            if event['type'] == 'call.ended':
                app.state.db.execute('INSERT OR IGNORE INTO endings VALUES (?, ?, ?)',
                                     (event['call_id'], int(time.time()), event['reason']))
                app.state.db.execute('DELETE FROM endings WHERE rowid NOT IN (SELECT rowid FROM endings ORDER BY rowid DESC LIMIT 1000)')
                if event['reason'] != 'taken':
                    remember_ended_call(event)
                app.state.db.commit()
            elif event['type'] == 'call.active':
                remember_active_call(event['call_id'])
            ws = app.state.sockets.get(user)
            if ws:
                try:
                    await send(ws, event)
                except Exception:
                    with suppress(Exception):
                        await asyncio.wait_for(ws.close(code=1011), 1)

    @app.get('/healthz')
    async def health():
        return {'status': 'ok', 'protocol': 1}

    @app.post('/internal/sessions')
    async def create_dynamic_session(request: Request):
        if not internal_authorized(request):
            raise HTTPException(status_code=401, detail='unauthorized')
        try:
            values = parse_qs((await request.body()).decode(), keep_blank_values=True)
            value = lambda key, default='': values.get(key, [default])[0]
            role = value('role')
            principal_id = value('principalId')
            target_id = value('targetId')
            allow = [target_id] if role == 'terminal' and target_id else []
            ttl = 900 if role == 'terminal' else 8 * 60 * 60
            connection_id, token, record = issue_session(
                app.state.sessions,
                principal_id=principal_id,
                role=role,
                allow=allow,
                label=value('displayName', principal_id),
                location=value('location'),
                ring_timeout=int(value('ringTimeoutSeconds', '30')),
                ttl_seconds=ttl,
            )
            return internal_response(request, {
                'version': 1,
                'connectionId': connection_id,
                'accessToken': token,
                'signalingUrl': app.state.public_signaling_url,
                'principalId': principal_id,
                'targetId': target_id,
                'expiresAt': record['expires_at'],
            }, status=201)
        except (TypeError, ValueError) as error:
            return internal_response(request, {'error': str(error)}, status=400)

    @app.get('/internal/calls/{call_id}')
    async def internal_call(call_id: str, request: Request):
        if not internal_authorized(request):
            raise HTTPException(status_code=401, detail='unauthorized')
        row = app.state.db.execute('''
            SELECT call_id, caller_principal, callee_principal, status,
                   requested_at, answered_at, ended_at, duration_seconds, reason
            FROM calls WHERE call_id = ?
        ''', (call_id,)).fetchone()
        if row is None:
            return internal_response(request, {'error': 'not_found'}, status=404)
        return internal_response(request, dict(zip((
            'callId', 'callerPrincipal', 'calleePrincipal', 'status',
            'requestedAt', 'answeredAt', 'endedAt', 'durationSeconds', 'reason',
        ), row)))

    @app.websocket('/ws')
    async def websocket(ws: WebSocket):
        origin = ws.headers.get('origin')
        if origin is not None and origin not in app.state.origins:
            await ws.close(code=1008)
            return
        await ws.accept()
        user = None
        registered = False
        try:
            raw = await asyncio.wait_for(ws.receive_text(), 10)
            if len(raw) > 2048:
                await ws.close(code=1009)
                return
            auth = json.loads(raw)
            if not isinstance(auth, dict) or auth.get('v') != 1 or auth.get('type') != 'auth':
                await ws.close(code=1008)
                return
            user = auth.get('device_id')
            dynamic_session = authenticate_session(
                app.state.sessions, user, auth.get('token'))
            static_session = authenticate(
                app.state.devices, user, auth.get('token'))
            if dynamic_session is None and not static_session:
                await ws.close(code=1008)
                return
            if dynamic_session is not None:
                principal = dynamic_session['principal_id']
                allow = dynamic_session['allow']
                metadata = {
                    'label': dynamic_session['label'],
                    'location': dynamic_session['location'],
                }
                ring_timeout = dynamic_session['ring_timeout']
            else:
                principal = user
                allow = app.state.devices[user]['allow']
                metadata = {'label': user, 'location': ''}
                ring_timeout = 30
            async with app.state.lock:
                try:
                    app.state.hub.connect(
                        user,
                        principal=principal,
                        allow=allow,
                        metadata=metadata,
                        ring_timeout=ring_timeout,
                    )
                except ProtocolError:
                    await send(ws, {'type': 'error', 'code': 'already_connected'})
                    await ws.close(code=1008)
                    return
                app.state.sockets[user] = ws
                registered = True
                await send(ws, {'type': 'ready', 'device_id': user,
                                'principal_id': principal,
                                'peers': allow,
                                'rtc': ice_config(user, app.state.urls, app.state.secret, app.state.policy)})
            seen = OrderedDict()
            window, count = time.monotonic(), 0
            while True:
                raw = await asyncio.wait_for(ws.receive_text(), 75)
                if len(raw) > 65536:
                    await ws.close(code=1009)
                    break
                msg = json.loads(raw)
                now = time.monotonic()
                if now - window >= 1:
                    window, count = now, 0
                count += 1
                if count > 100:
                    await ws.close(code=1008)
                    break
                if not isinstance(msg, dict):
                    raise ValueError('invalid_message')
                mid = msg.get('id')
                if msg.get('v') != 1 or not isinstance(mid, str) or not 1 <= len(mid) <= 100:
                    await send(ws, {'type': 'error', 'code': 'invalid_envelope'})
                    continue
                async with app.state.lock:
                    if mid in seen:
                        await send(ws, seen[mid])
                        continue
                    try:
                        await deliver(app.state.hub.expire())
                        result, events = app.state.hub.handle(user, msg)
                        response = {'type': 'ack', 'id': mid, **result}
                        if msg.get('type') == 'call.invite':
                            remember_started_call(
                                app.state.hub.calls[result['call_id']])
                        if msg.get('type') == 'call.accept':
                            # Refresh TURN credentials before each accepted call.
                            cid = msg['call_id']
                            call = app.state.hub.calls[cid]
                            remember_answered_call(call)
                            for p in (call.caller, call.callee):
                                events.insert(0, (p, {'type': 'rtc.config', 'call_id': cid,
                                    'rtc': ice_config(p, app.state.urls, app.state.secret, app.state.policy)}))
                    except ProtocolError as exc:
                        response, events = {'type': 'error', 'id': mid, 'code': str(exc)}, []
                    seen[mid] = response
                    if len(seen) > 256:
                        seen.popitem(last=False)
                    await send(ws, response)
                    await deliver(events)
        except WebSocketDisconnect:
            # The peer already completed the WebSocket close handshake. Sending
            # another close frame here can leave ASGI test clients waiting and
            # delays the disconnect event sent to the other call participant.
            pass
        except (asyncio.TimeoutError, ValueError, TypeError):
            with suppress(Exception):
                await ws.close(code=1008)
        finally:
            if registered:
                async with app.state.lock:
                    if app.state.sockets.get(user) is ws:
                        app.state.sockets.pop(user, None)
                        await deliver(app.state.hub.disconnect(user))

    return app


app = create_app()
