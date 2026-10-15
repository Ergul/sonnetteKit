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
                              db_path=str(tmp_path / 'calls.db'), origins=['http://localhost:8080'],
                              internal_key='x' * 32,
                              public_signaling_url='wss://call.example/ws')) as client:
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


def dynamic_session(api, **values):
    response = api.post(
        '/internal/sessions',
        headers={'x-internal-api-key': 'x' * 32},
        data=values,
    )
    assert response.status_code == 201
    return response.json()


def test_internal_session_plain_text_contract_for_appserver(api):
    response = api.post(
        '/internal/sessions',
        headers={
            'x-internal-api-key': 'x' * 32,
            'accept': 'text/plain',
        },
        data={
            'role': 'terminal',
            'principalId': 'door-plain',
            'targetId': 'operator-plain',
        },
    )
    assert response.status_code == 201
    values = dict(
        line.split('=', 1)
        for line in response.text.splitlines()
        if '=' in line
    )
    assert values['signalingUrl'] == 'wss://call.example/ws'
    assert values['targetId'] == 'operator-plain'
    assert values['connectionId'].startswith('terminal-')
    assert values['accessToken']


def test_internal_routes_require_the_server_key(api):
    assert api.post('/internal/sessions', data={}).status_code == 401
    assert api.get('/internal/calls/unknown').status_code == 401


def test_dynamic_route_rings_every_operator_tab_and_audits(api):
    door = dynamic_session(
        api,
        role='terminal',
        principalId='door-1',
        targetId='operator-1',
        displayName='Entrée',
        location='Accueil',
        ringTimeoutSeconds='20',
    )
    operator1 = dynamic_session(
        api, role='operator', principalId='operator-1',
        displayName='Bureau')
    operator2 = dynamic_session(
        api, role='operator', principalId='operator-1',
        displayName='Bureau')

    with api.websocket_connect('/ws') as door_ws:
        auth(door_ws, door['connectionId'], door['accessToken'])
        with api.websocket_connect('/ws') as operator_ws_1:
            auth(operator_ws_1, operator1['connectionId'],
                 operator1['accessToken'])
            with api.websocket_connect('/ws') as operator_ws_2:
                auth(operator_ws_2, operator2['connectionId'],
                     operator2['accessToken'])
                door_ws.send_json({
                    'v': 1,
                    'id': 'dynamic-invite',
                    'type': 'call.invite',
                    'to': 'operator-1',
                })
                cid = door_ws.receive_json()['call_id']
                assert door_ws.receive_json()['type'] == 'call.ringing'
                assert operator_ws_1.receive_json()['type'] == 'call.incoming'
                assert operator_ws_2.receive_json()['type'] == 'call.incoming'

                operator_ws_1.send_json({
                    'v': 1,
                    'id': 'dynamic-accept',
                    'type': 'call.accept',
                    'call_id': cid,
                })
                assert operator_ws_1.receive_json()['type'] == 'ack'
                assert operator_ws_1.receive_json()['type'] == 'rtc.config'
                assert operator_ws_1.receive_json()['type'] == 'call.accepted'
                taken = operator_ws_2.receive_json()
                assert taken['type'] == 'call.ended'
                assert taken['reason'] == 'taken'
                assert door_ws.receive_json()['type'] == 'rtc.config'
                assert door_ws.receive_json()['type'] == 'call.accepted'

                door_ws.send_json({
                    'v': 1,
                    'id': 'dynamic-end',
                    'type': 'call.end',
                    'call_id': cid,
                })
                assert door_ws.receive_json()['type'] == 'ack'
                assert door_ws.receive_json()['type'] == 'call.ended'
                assert operator_ws_1.receive_json()['type'] == 'call.ended'

    audit = api.get(
        f'/internal/calls/{cid}',
        headers={'x-internal-api-key': 'x' * 32},
    )
    assert audit.status_code == 200
    assert audit.json()['callerPrincipal'] == 'door-1'
    assert audit.json()['calleePrincipal'] == 'operator-1'
    assert audit.json()['status'] == 'ended'
