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
args = parser.parse_args()
os.umask(0o077)
root = Path(args.output)
root.mkdir(parents=True, exist_ok=True)
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
TURN_REALM=turn.example.com
TURN_URLS=turns:turn.example.com:443?transport=tcp
ICE_POLICY=relay
ALLOWED_ORIGINS=https://call.example.com
# Native clients without Origin are allowed; browser origins must match exactly.
# Keep empty for a directly addressed host; use PUBLIC_IP/PRIVATE_IP for NAT.
TURN_EXTERNAL_IP=
TURN_RELAY_IP=
''')
(root / 'certs').mkdir(exist_ok=True)
print(f'Created credentials in {root}. Device IDs: door, desk. Keys were NOT printed.')
print('Read device-keys.json locally and enter each device key in its client.')
