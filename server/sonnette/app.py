"""Run exactly one Uvicorn worker: call state and sockets live in this process."""
import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager, suppress
import json
import os
from pathlib import Path
import sqlite3
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from .core import Hub, ProtocolError
from .security import authenticate, ice_config, load_devices


def create_app(devices=None, turn_urls=None, secret=None, policy=None, db_path=None, origins=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.devices = devices if devices is not None else load_devices(os.getenv('DEVICES_FILE', '/config/devices.json'))
        app.state.urls = turn_urls if turn_urls is not None else [u for u in os.getenv('TURN_URLS', '').split(',') if u]
        app.state.secret = secret if secret is not None else Path(os.environ['TURN_SECRET_FILE']).read_text().strip() if os.getenv('TURN_SECRET_FILE') else ''
        app.state.policy = policy or os.getenv('ICE_POLICY', 'all')
        ice_config('startup', app.state.urls, app.state.secret, app.state.policy)
        app.state.origins = origins if origins is not None else os.getenv('ALLOWED_ORIGINS', '').split(',')
        app.state.hub = Hub({u: d['allow'] for u, d in app.state.devices.items()})
        app.state.sockets = {}
        app.state.lock = asyncio.Lock()
        path = db_path or os.getenv('DATABASE_PATH', '/data/calls.sqlite3')
        app.state.db = sqlite3.connect(path, check_same_thread=False)
        app.state.db.execute('CREATE TABLE IF NOT EXISTS endings (call_id TEXT PRIMARY KEY, ended_at INTEGER, reason TEXT)')
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

    async def send(ws, payload):
        await asyncio.wait_for(ws.send_json({'v': 1, **payload}), timeout=3)

    async def deliver(events):
        # Called under lock. Bounded sends prevent a slow peer blocking indefinitely.
        for user, event in events:
            if event['type'] == 'call.ended':
                app.state.db.execute('INSERT OR IGNORE INTO endings VALUES (?, ?, ?)',
                                     (event['call_id'], int(time.time()), event['reason']))
                app.state.db.execute('DELETE FROM endings WHERE rowid NOT IN (SELECT rowid FROM endings ORDER BY rowid DESC LIMIT 1000)')
                app.state.db.commit()
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
            if not isinstance(auth, dict) or auth.get('v') != 1 or auth.get('type') != 'auth' or not authenticate(app.state.devices, auth.get('device_id'), auth.get('token')):
                await ws.close(code=1008)
                return
            user = auth['device_id']
            async with app.state.lock:
                try:
                    app.state.hub.connect(user)
                except ProtocolError:
                    await send(ws, {'type': 'error', 'code': 'already_connected'})
                    await ws.close(code=1008)
                    return
                app.state.sockets[user] = ws
                registered = True
                await send(ws, {'type': 'ready', 'device_id': user,
                                'peers': app.state.devices[user]['allow'],
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
                        if msg.get('type') == 'call.accept':
                            # Refresh TURN credentials before each accepted call.
                            cid = msg['call_id']
                            call = app.state.hub.calls[cid]
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
        except (WebSocketDisconnect, asyncio.TimeoutError, ValueError, TypeError):
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
