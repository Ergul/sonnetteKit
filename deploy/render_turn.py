"""Render secret-bearing coturn configuration at runtime, never at image build."""
import ipaddress
import os
from pathlib import Path
import re


def render():
    secret = Path(os.getenv('TURN_SECRET_FILE', '/run/secrets/turn-secret')).read_text().strip()
    realm = os.environ['TURN_REALM']
    if not re.fullmatch(r'[a-zA-Z0-9.-]+', realm) or not re.fullmatch(r'[a-zA-Z0-9_-]{32,}', secret):
        raise ValueError('Invalid TURN realm or secret')
    lines = [
        'listening-port=3478', 'tls-listening-port=5349', 'listening-ip=0.0.0.0',
        f'realm={realm}', 'use-auth-secret', f'static-auth-secret={secret}',
        'fingerprint', 'no-cli', 'no-multicast-peers', 'no-tcp-relay',
        'no-tlsv1', 'no-tlsv1_1', 'no-dtls',
        'min-port=49160', 'max-port=49200',
        'user-quota=4', 'total-quota=100', 'max-bps=1000000',
        'cert=/certs/fullchain.pem', 'pkey=/certs/privkey.pem',
        'log-file=stdout', 'simple-log', 'pidfile=/tmp/coturn.pid',
        # Restrict common private ranges to prevent the relay reaching internal services.
        # Internal-only mode explicitly permits only the relay's own address.
        'denied-peer-ip=0.0.0.0-0.255.255.255',
        'denied-peer-ip=10.0.0.0-10.255.255.255',
        'denied-peer-ip=127.0.0.0-127.255.255.255',
        'denied-peer-ip=169.254.0.0-169.254.255.255',
        'denied-peer-ip=192.168.0.0-192.168.255.255',
        'denied-peer-ip=172.16.0.0-172.31.255.255',
        'denied-peer-ip=::1', 'denied-peer-ip=fc00::-fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff',
        'denied-peer-ip=fe80::-febf:ffff:ffff:ffff:ffff:ffff:ffff:ffff',
    ]
    external = os.getenv('TURN_EXTERNAL_IP', '')
    relay = os.getenv('TURN_RELAY_IP', '')
    if external:
        for ip in external.split('/'):
            ipaddress.ip_address(ip)
        lines.append(f'external-ip={external}')
    if relay:
        ipaddress.ip_address(relay)
        lines.append(f'relay-ip={relay}')
    # Explicit peer pinning for the experimental internal-relay-only profile.
    if os.getenv('TURN_INTERNAL_ONLY') == '1':
        if not relay or external:
            raise ValueError('Internal-only mode requires TURN_RELAY_IP and no external mapping')
        lines += ['denied-peer-ip=0.0.0.0-255.255.255.255',
                  'denied-peer-ip=::-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff',
                  f'allowed-peer-ip={relay}']
    os.umask(0o077)
    Path('/tmp/turnserver.conf').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    render()
