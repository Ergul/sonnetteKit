# Test plan

## Automated gates

1. Run `python -m pytest -q` from `server/`.
2. Generate demo runners using `python3 scripts/bootstrap_flutter.py --platforms web`.
3. In `packages/sonnette_kit`, run `flutter pub get`, `flutter analyze`, `flutter test`.
4. In `apps/flutter_client`, run `flutter analyze`, `flutter build web`.
5. Generate test credentials and a disposable TURN certificate, then start each Docker layout with `up --build --wait`. Check `/healthz`, both service health checks and logs. A disposable/self-signed certificate is sufficient for listener smoke tests, not real-browser TURN validation.
6. Run `nginx -t` against the integrated production configuration before any reload.

GitHub Actions runs gates 1–5 (the experimental container layouts). Gate 6 requires the actual Nginx configuration. Do not treat a workflow definition as evidence of a passing run.

## First real call

Use separate devices/headphones and valid trusted certificates. Keep both apps open.

- Connect `door` and `desk` with different keys.
- Initiate a call, accept, confirm bidirectional audio AND video.
- Toggle microphone and camera; confirm the remote experience.
- Hang up from each side and immediately call again.
- Decline, let ringing time out, call an offline device, and attempt crossed invitations.
- Deny camera/microphone permission and verify that both devices return to idle.
- Disconnect a client network during a call; confirm call termination, signaling reconnection and successful manual redial.
- Restart signaling; verify neither device stays permanently busy.
- Test Android ↔ Web, Windows ↔ Android, macOS ↔ Android, and target browsers independently.

## Experimental TCP-443-only acceptance

This profile is intentionally marked experimental until the following evidence is recorded:

1. Confirm merged Compose output exposes only loopback TCP 8000/5349 and no public UDP ports.
2. Confirm only Nginx TCP 443 is reachable from outside the server network. Docker can publish ports independently of some host firewall tools; inspect actual mappings and gateway rules.
3. Both clients receive only the configured `turns:...:443?transport=tcp` server and `iceTransportPolicy=relay`.
4. Capture/inspect the TLS ClientHello for the TURN connection: confirm SNI is the TURN hostname on every runtime. Do not assume it from a browser HTTPS test.
5. Confirm Nginx routes TURN to coturn, not to the HTTP fallback.
6. Inspect WebRTC selected candidate pairs (e.g. browser WebRTC diagnostics): both ends must use relay candidates.
7. Confirm relay allocations use the server's internal Docker address and same-server peer traffic stays internal.
8. Perform a 15-minute call across unrelated Internet networks, including a mobile connection and the intended Fortinet configuration.
9. Verify the negative case: a client configured with a different TURN instance is not expected to work with internal-only relay addresses.
10. Test packet loss/congestion; TCP head-of-line blocking can increase delay.

If SNI is absent, this shared-IP SNI template cannot select the TURN backend reliably. Options include a separate public IP for TURN on 443, or a different tested Layer-4 routing strategy. If the gateway insists on actual HTTPS application traffic, TURN/TLS may remain blocked even on 443. A plain HTTP `location /turn` is not a fix.

## Results to record

For each test: date, server commit, deployment profile, device OS/version, Flutter/browser version, network type, selected ICE pair, result and relevant redacted logs. Never attach device keys, TURN shared secrets, private keys or unredacted SDP to a public issue.
