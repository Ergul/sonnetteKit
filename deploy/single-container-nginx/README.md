# Single-container deployment behind Nginx

This generic example runs the signaling server and coturn in one container.
Nginx may run on the same host or on a separate reverse-proxy host. Replace all
example domains and RFC 5737 documentation addresses before deployment.

## DNS and network

- `signaling.example.com` serves HTTPS and WebSocket signaling.
- `turn.example.com` serves TURN TLS on TCP port 5349.
- Nginx proxies signaling to the Docker host's TCP port 8000.
- Nginx terminates TURN TLS and proxies plain TURN/TCP to the Docker host's TCP
  port 3478.
- Forward public UDP ports 49160-49200 without port translation to the Docker
  host's same UDP range.

The public UDP relay range is required even when clients connect to TURN over
TLS/TCP. The `transport=tcp` URI parameter describes the client-to-TURN
connection; coturn still allocates UDP relay sockets for WebRTC media. Do not
expose the signaling or plain TURN backend ports to the public Internet.

## Provision and start

From the repository root on the Docker host:

```bash
python3 scripts/provision.py \
  --signaling-domain signaling.example.com \
  --turn-domain turn.example.com \
  --turn-port 5349 \
  --allowed-origins https://app.example.com \
  --turn-external-ip 203.0.113.10/172.30.44.10 \
  --turn-relay-ip 172.30.44.10
docker compose --env-file secrets/compose.env \
  -f deploy/single-container-nginx/compose.yaml config
docker compose --env-file secrets/compose.env \
  -f deploy/single-container-nginx/compose.yaml up --build -d
```

Set `SIGNALING_BIND_ADDRESS`, `SIGNALING_PORT`, `TURN_BIND_ADDRESS`,
`TURN_TCP_PORT`, `TURN_RELAY_BIND_ADDRESS`, `TURN_RELAY_MIN_PORT`,
`TURN_RELAY_MAX_PORT`, or `CONTAINER_NAME` in `secrets/compose.env` if the
defaults do not match the target host. The explicit `--env-file` makes those
values available while Compose interpolates `ports:`; the service-level
`env_file:` alone only passes them into the running container. Bind the backend
ports to a private interface, rather than `127.0.0.1`, when Nginx is on another
host, and restrict that interface with firewall rules. Forward the configured
relay range without port translation.

The combined image also starts an internal TLS listener. Therefore
`.local/certs` must contain a key and certificate readable by UID 10001. They
may be self-signed because public TURN TLS is terminated by Nginx in this
topology.

Keep `.local/compose.env` and `.local/turn-secret` secret. Configure the
application server with `SONNETTE_INTERNAL_URL` pointing to the private
signaling backend and copy `INTERNAL_API_KEY` to `SONNETTE_INTERNAL_KEY`.

## Nginx and certificates

Install `nginx-signaling.conf` as an HTTP site. Replace the example domain,
backend address and port, then obtain its certificate with Certbot. Install
`nginx-turn-stream.conf` at Nginx top level after obtaining the TURN
certificate. On Ubuntu, an include such as the following belongs outside
`http {}`:

```nginx
include /etc/nginx/streams-enabled/*.conf;
```

Use `nginx-turn-acme.conf` for the TURN certificate HTTP challenge:

```bash
sudo mkdir -p /var/www/certbot/.well-known/acme-challenge
sudo chmod 755 /var/www/certbot
sudo certbot certonly --webroot -w /var/www/certbot -d turn.example.com \
  --deploy-hook "systemctl reload nginx"
```

### ACME webroot versus certificate storage

`/var/www/certbot` is not a certificate directory. It is only the HTTP webroot
used during the ACME ownership challenge. Certbot creates a short-lived file
below `/var/www/certbot/.well-known/acme-challenge/`, which Let's Encrypt
retrieves through the port-80 TURN virtual host.

The issued TURN certificate is stored in Certbot's standard location:

```text
/etc/letsencrypt/live/turn.example.com/fullchain.pem
/etc/letsencrypt/live/turn.example.com/privkey.pem
```

The Nginx stream service reads those paths directly. Certbot maintains the
symlinks during renewal, and the deploy hook reloads Nginx so that it uses the
renewed certificate.

Do not use `certbot --nginx` for the TURN hostname. The Nginx plugin is intended
for HTTP/HTTPS virtual hosts and may add or modify a public HTTPS listener on
port 443. The TURN hostname is instead a TURN TLS endpoint on port 5349.
`certbot certonly --webroot` obtains and renews its certificate without
rewriting the TURN topology.

The signaling hostname is a normal HTTP/WebSocket virtual host, so its
certificate can safely be installed with:

```bash
sudo certbot --nginx -d signaling.example.com
```

Always run `nginx -t` before reloading Nginx.
