# Deployment behind an existing Nginx

## Assumptions

- Linux Docker host; Nginx runs on that same host, outside this project.
- Two DNS names, e.g. `call.example.com` and `turn.example.com`, point to the host's public IPv4 address.
- Trusted certificates exist for both names. Use DNS-01 issuance if TCP 80 must remain closed. Certificate automation is not provided by this repository.
- Docker Compose 2.24.4+ for the experimental override syntax.
- The Docker subnet `172.30.44.0/24` does not overlap your infrastructure. If it does, update all Compose network/relay addresses together.
- Back up the current Nginx configuration before integrating the templates. They are fragments, not replacements for your production configuration.

## 1. Provision devices

```bash
python3 scripts/provision.py
```

Edit `.local/compose.env`. Set `TURN_REALM`, `TURN_URLS` and `ALLOWED_ORIGINS` to your actual domains. Browser origins must match scheme, hostname and port exactly. A comma-separated list is supported (no spaces). Native clients normally have no Origin header.

Example:

```dotenv
TURN_REALM=turn.example.com
TURN_URLS=turns:turn.example.com:443?transport=tcp
ICE_POLICY=relay
ALLOWED_ORIGINS=https://call.example.com
TURN_EXTERNAL_IP=
TURN_RELAY_IP=
```

For standard Docker networking, set `TURN_RELAY_IP=172.30.44.10` and `TURN_EXTERNAL_IP=YOUR_PUBLIC_IP/172.30.44.10`. The public UDP relay range must reach coturn on identical ports. On a Fortinet/NAT gateway, forward that range and TCP 443 to the Docker/Nginx host. The experimental profile overrides both settings and keeps relay allocations on the Docker network.

Provisioning is a development bootstrap, not a public registration endpoint. Add other devices by generating a random 32-byte-or-longer key, storing its SHA-256 digest under `token_sha256`, and defining its `allow` list. Keys must not be human passwords. Never embed a shared server-wide secret in Flutter.

## 2. Certificates and file ownership

Copy the TURN certificate and private key into:

- `.local/certs/fullchain.pem`
- `.local/certs/privkey.pem`

The application containers run as UID/GID 10001. Make only their input files readable by that user:

```bash
sudo chown 10001:10001 .local/devices.json .local/turn-secret
sudo chown -R 10001:10001 .local/certs
sudo chmod 700 .local/certs
sudo chmod 600 .local/devices.json .local/turn-secret .local/certs/privkey.pem
sudo chmod 644 .local/certs/fullchain.pem
```

Keep `.local/device-keys.json` private to the operator; it is never mounted into containers. Do not make secret files world-readable. Configure certificate renewal to refresh the mounted TURN files and restart coturn/the combined container. Do not mount only a symlink whose target is outside the mounted directory.

Named `call-data` volumes persist the SQLite log. Both deployment layouts use the same volume name within the same Compose project. Preserve the same project name when switching. Do not run both layouts simultaneously. Stop the old layout before starting the new one; do not use `down -v` unless deleting history is intentional.

## 3. Configure Nginx

Check module support with `nginx -V` and inspect your distribution's module-loading configuration. `stream` and `stream_ssl_preread` must be available and, where packaged dynamically, loaded at the top level.

Integrate:

- `deploy/nginx/stream.conf` at **top level**, outside `http {}`.
- `deploy/nginx/site.conf` **inside** `http {}`.

Do not create two independent `stream {}` sections if one already exists; merge the contents. Likewise, adapt shared map names if necessary.

The stream listener owns public TCP 443. Move all existing HTTPS listeners on that same IP to `127.0.0.1:8443` (and retain their certificates and server names). Unknown/default SNI is forwarded there. `turn.example.com` goes directly to coturn's local TCP 5349 listener. Nginx does not decrypt that TURN connection; coturn terminates TLS.

This basic template intentionally does not enable PROXY protocol. HTTP access logs will see the local stream proxy address; do not base production IP-rate-limiting or IP access rules on that address. Client-IP preservation needs a coordinated PROXY-protocol configuration for the HTTP branch. Do not send a PROXY header to the TURN branch without explicit coturn support/configuration.

```bash
sudo nginx -t
sudo systemctl reload nginx
```

If Nginx is on another machine or in another container, the loopback addresses in these examples are not appropriate. Bind the backend ports to a private interface and restrict them to that Nginx host, or attach Nginx to the Docker network and use service DNS names. Never expose the unauthenticated HTTP transport publicly without TLS.

## 4. Choose a profile

| Profile | Public exposure | Purpose |
| --- | --- | --- |
| Standard | Nginx TCP 443, TURN UDP 3478 and UDP 49160–49200 | Baseline relay connectivity |
| Experimental 443-only | Nginx TCP 443 only | Both endpoints forced through the same internal TURN relay |

For standard mode, UDP 3478 is only useful if you add `turn:turn.example.com:3478?transport=udp` to `TURN_URLS`. UDP relay allocations are still required for conventional relay-to-peer traffic even when client-to-TURN uses TLS.

Before starting, inspect merged configuration:

```bash
docker compose -f compose.yaml -f compose.443.yaml config
docker compose -f compose.yaml -f compose.443.yaml up --build -d
docker compose -f compose.yaml -f compose.443.yaml ps
```

The experimental mode assigns relay address `172.30.44.10`, forces `ICE_POLICY=relay`, and allows coturn to send peer traffic only to its own address. Both endpoints must use this same instance. It is not a general-purpose public TURN configuration. Check selected ICE candidate pairs and complete the test plan before accepting this topology. SNI may differ between WebRTC implementations; a connection sent to the HTTP backend instead of TURN will fail.

## 5. Flutter Web hosting

Build the demo with `flutter build web` after generating runners. Copy `apps/flutter_client/build/web/` to the Nginx root configured in `site.conf`, e.g. `/var/www/sonnette`. The server image does not embed or serve the Flutter bundle. For an existing Flutter host application, deploy that application's build instead.

Use `wss://call.example.com/ws`. Public camera/microphone access requires a secure browser context and user permission. `localhost` is the local development exception.

## Operations

- Use exactly one Uvicorn worker. Redis/distributed state is not implemented.
- Health checks verify signaling HTTP and/or the TURN TCP listener, not ICE/media, valid certificates or successful authentication.
- On restart, active calls are not persisted. Clients reconnect but do not automatically redial.
- Monitor Docker health, exits, CPU and network usage. The combined container uses supervisord to restart either child; an unhealthy container is not automatically restarted by Docker merely because its health status is unhealthy.
- Call-ending history retains at most 1,000 entries with call ID, timestamp and reason. Application payloads and media are not stored. Coturn/network logs can contain IP addresses; configure operational retention separately.
- TURN bandwidth is capped at 1,000,000 bytes/s per session in the template. Tune the cap and quotas only after measuring your use case.
