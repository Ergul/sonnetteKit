import hashlib
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sonnette.app import create_app


@pytest.fixture
def api(tmp_path):
    devices = {u: {'token_sha256': hashlib.sha256(f'{u}-key'.encode()).hexdigest(), 'allow': [p]}
               for u, p in [('a', 'b'), ('b', 'a')]}
    with TestClient(create_app(devices=devices, turn_urls=[], secret='', policy='all',
                              db_path=str(tmp_path / 'calls.db'), origins=['http://localhost:8080'])) as client:
        yield client


def auth(ws, user, key=None):
    ws.send_json({'v': 1, 'type': 'auth', 'device_id': user, 'token': key or f'{user}-key'})
    return ws.receive_json()


def test_health_and_auth(api):
    assert api.get('/healthz').json()['status'] == 'ok'
    with api.websocket_connect('/ws') as ws:
        ready = auth(ws, 'a')
        assert ready['type'] == 'ready'
        assert ready['peers'] == ['b']
        assert ready['rtc']['iceServers'] == []


def test_wrong_key_and_origin(api):
    with pytest.raises(WebSocketDisconnect):
        with api.websocket_connect('/ws') as ws:
            auth(ws, 'a', 'bad')
    with pytest.raises(WebSocketDisconnect):
        with api.websocket_connect('/ws', headers={'origin': 'https://evil.example'}) as ws:
            auth(ws, 'a')


def test_duplicate_session_does_not_disconnect_original(api):
    with api.websocket_connect('/ws') as a:
        auth(a, 'a')
        with api.websocket_connect('/ws') as duplicate:
            assert auth(duplicate, 'a')['code'] == 'already_connected'
        a.send_json({'v': 1, 'id': 'still-here', 'type': 'ping'})
        assert a.receive_json()['type'] == 'ack'


def test_call_replay_and_disconnect(api):
    with api.websocket_connect('/ws') as a:
        auth(a, 'a')
        with api.websocket_connect('/ws') as b:
            auth(b, 'b')
            invitation = {'v': 1, 'id': 'invite-1', 'type': 'call.invite', 'to': 'b'}
            a.send_json(invitation)
            ack = a.receive_json()
            cid = ack['call_id']
            assert a.receive_json()['type'] == 'call.ringing'
            assert b.receive_json()['type'] == 'call.incoming'
            a.send_json(invitation)
            assert a.receive_json() == ack  # no second incoming call event
            b.send_json({'v': 1, 'id': 'accept-1', 'type': 'call.accept', 'call_id': cid})
            assert b.receive_json()['type'] == 'ack'
            assert b.receive_json()['type'] == 'rtc.config'
            assert b.receive_json()['type'] == 'call.accepted'
            assert a.receive_json()['type'] == 'rtc.config'
            assert a.receive_json()['type'] == 'call.accepted'
            a.send_json({'v': 1, 'id': 'offer', 'type': 'rtc.offer', 'call_id': cid, 'sdp': 'v=0'})
            assert a.receive_json()['type'] == 'ack'
            assert b.receive_json()['sdp'] == 'v=0'
        assert a.receive_json()['reason'] == 'disconnected'


def test_malformed_json_and_size(api):
    with pytest.raises(WebSocketDisconnect):
        with api.websocket_connect('/ws') as ws:
            auth(ws, 'a')
            ws.send_text('not-json')
            ws.receive_json()
    with pytest.raises(WebSocketDisconnect):
        with api.websocket_connect('/ws') as ws:
            auth(ws, 'a')
            ws.send_text('x' * 65537)
            ws.receive_json()
