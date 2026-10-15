#!/usr/bin/env python3
"""Generate a local test pair. Never commit the output directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets

parser = argparse.ArgumentParser()
parser.add_argument('--output', default='.local')
parser.add_argument('--signaling-domain', default='call.example.com')
parser.add_argument('--turn-domain', default='turn.example.com')
parser.add_argument('--turn-port', type=int, default=443)
parser.add_argument('--allowed-origins', default='https://call.example.com')
parser.add_argument('--turn-external-ip', default='')
parser.add_argument('--turn-relay-ip', default='')
args = parser.parse_args()
os.umask(0o077)
root = Path(args.output)
root.mkdir(parents=True, exist_ok=True)
if not 1 <= args.turn_port <= 65535:
    raise SystemExit('TURN port must be between 1 and 65535.')
files = ['devices.json', 'device-keys.json', 'turn-secret', 'compose.env']
if any((root / f).exists() for f in files):
    raise SystemExit('Refusing to replace existing credentials; choose a new directory for rotation.')
keys = {name: secrets.token_urlsafe(32) for name in ['door', 'desk']}
records = {name: {'token_sha256': hashlib.sha256(key.encode()).hexdigest(),
                  'allow': [peer for peer in keys if peer != name]} for name, key in keys.items()}
(root / 'devices.json').write_text(json.dumps(records, indent=2) + '\n')
(root / 'device-keys.json').write_text(json.dumps(keys, indent=2) + '\n')
(root / 'turn-secret').write_text(secrets.token_hex(32) + '\n')
(root / 'compose.env').write_text('''# Edit these values before launching Docker.
INTERNAL_API_KEY={internal_api_key}
PUBLIC_SIGNALING_URL=wss://{signaling_domain}/ws
TURN_REALM={turn_domain}
TURN_URLS=turns:{turn_domain}:{turn_port}?transport=tcp
ICE_POLICY=relay
ALLOWED_ORIGINS={allowed_origins}
# Native clients without Origin are allowed; browser origins must match exactly.
# Keep empty for a directly addressed host; use PUBLIC_IP/PRIVATE_IP for NAT.
TURN_EXTERNAL_IP={turn_external_ip}
TURN_RELAY_IP={turn_relay_ip}
'''.format(
    internal_api_key=secrets.token_urlsafe(48),
    signaling_domain=args.signaling_domain,
    turn_domain=args.turn_domain,
    turn_port=args.turn_port,
    allowed_origins=args.allowed_origins,
    turn_external_ip=args.turn_external_ip,
    turn_relay_ip=args.turn_relay_ip,
))
(root / 'certs').mkdir(exist_ok=True)
print(f'Created credentials in {root}. Device IDs: door, desk. Keys were NOT printed.')
print('Read device-keys.json locally and enter each device key in its client.')
