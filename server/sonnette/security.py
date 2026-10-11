import base64
import hashlib
import hmac
import json
import re
import time
from pathlib import Path


def load_devices(path):
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or not data:
        raise ValueError('At least one provisioned device is required')
    for user, record in data.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', user):
            raise ValueError('Invalid device ID')
        if not re.fullmatch(r'[0-9a-f]{64}', record['token_sha256']):
            raise ValueError('Invalid token hash')
        if not isinstance(record['allow'], list) or any(p not in data or p == user for p in record['allow']):
            raise ValueError('Invalid allow list')
    return data


def authenticate(devices, user, token):
    # Tokens are randomly generated 256-bit keys, not human passwords.
    if not isinstance(user, str) or not isinstance(token, str) or len(token) > 256:
        return False
    expected = devices.get(user, {}).get('token_sha256', '0' * 64)
    return hmac.compare_digest(expected, hashlib.sha256(token.encode()).hexdigest()) and user in devices


def ice_config(user, urls, secret, policy, now=None):
    if policy not in ('all', 'relay'):
        raise ValueError('ICE_POLICY must be all or relay')
    if policy == 'relay' and not urls:
        raise ValueError('Relay mode requires TURN_URLS')
    servers = []
    if urls:
        if len(secret) < 32 or any(not u.startswith(('turn:', 'turns:')) for u in urls):
            raise ValueError('A TURN secret of at least 32 characters and TURN URLs are required')
        # Supports the 1-hour call limit plus connection/setup time.
        username = f'{int(time.time() if now is None else now) + 7200}:{user}'
        credential = base64.b64encode(hmac.new(secret.encode(), username.encode(), hashlib.sha1).digest()).decode()
        servers.append({'urls': urls, 'username': username, 'credential': credential})
    return {'iceServers': servers, 'iceTransportPolicy': policy, 'sdpSemantics': 'unified-plan'}
