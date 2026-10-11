# sonnetteKit

Self-hosted, one-to-one audio/video calling with an **embeddable Flutter widget**, a small Python signaling server, and coturn. No LiveKit dependency.

**Status: initial test version, not a production release.** The server implements a real call state machine and the Flutter package implements WebRTC offer/answer and ICE exchange. Real-device media, native permissions, restrictive networks and the experimental TCP-443-only topology still require validation. See [test plan](docs/testing.md) and [validation record](docs/validation.md).

## What is included

- `SonnetteCallWidget`: a Material widget to embed in an existing Flutter application.
- `SonnetteClient`: a reusable controller, also usable with your own UI.
- Authenticated device identities and explicit outgoing-call allow lists.
- Incoming calls, accept/decline, busy/offline responses, timeout, hang-up, microphone and camera controls.
- Signaling reconnection after transport loss. **Interrupted calls end; they are not resumed automatically.**
- Short-lived TURN credentials and a bounded SQLite log of call endings (no media or SDP storage).
- Split Docker deployment and a single-container deployment using the same code.
- Nginx templates for an existing, file-configured reverse proxy.
- An **experimental** TCP-443-only profile, separate from the standard networking profile.

## Repository

| Path | Purpose |
| --- | --- |
| `packages/sonnette_kit/` | Flutter widget and controller |
| `apps/flutter_client/` | Integration demo, not a separate product requirement |
| `server/` | FastAPI WebSocket signaling server and tests |
| `deploy/` | Container images, runtime TURN config and Nginx examples |
| `compose*.yaml` | Standard and experimental deployment variants |
| `scripts/` | Credential provisioning and Flutter runner generation |
| `docs/` | Installation, integration, protocol and test documentation |

## Embed the Flutter widget

Until a package release is published, reference this repository:

```yaml
dependencies:
  sonnette_kit:
    git:
      url: https://github.com/Ergul/sonnetteKit.git
      path: packages/sonnette_kit
      ref: main # Pin a reviewed commit SHA in your application.
```

Your application creates and authenticates the controller, then embeds the widget:

```dart
import 'package:sonnette_kit/sonnette_kit.dart';

final client = SonnetteClient();

await client.connect(
  server: Uri.parse('wss://call.example.com/ws'),
  id: deviceId,
  token: deviceAccessKey,
);

// In a Material app's widget tree:
SizedBox(
  height: 620,
  child: SonnetteCallWidget(
    client: client,
    targetDeviceId: 'desk', // Optional: omit to show all authorized destinations.
    title: 'Reception',
  ),
);

// When the host no longer needs the controller:
await client.shutdown();
client.dispose();
```

The host owns the controller and its lifetime. The widget does not introduce a `MaterialApp`, navigation, account system or credential storage. Keep the controller alive at application scope to receive calls while navigating within the app. Receiving calls when the app is closed/backgrounded requires additional OS integration and is **not included** yet. See [Flutter integration](docs/flutter-integration.md).

## First local signaling test

Requirements: Python 3.12+, Flutter stable with Dart 3.6+.

```bash
python3 scripts/provision.py
python3 -m venv .venv
. .venv/bin/activate
pip install -r server/requirements-dev.txt
cd server
python -m pytest -q
cd ..
```

The provisioning command creates `.local/devices.json`, `.local/device-keys.json`, a TURN secret and a deployment environment template. **All are ignored by Git.** Read the two generated device keys locally; do not paste them into issues or commits.

Start the development server (from the repository root):

```bash
DEVICES_FILE="$PWD/.local/devices.json" \
DATABASE_PATH="$PWD/.local/calls.sqlite3" \
ALLOWED_ORIGINS=http://localhost:8080 \
ICE_POLICY=all \
.venv/bin/uvicorn sonnette.app:app --app-dir server --host 127.0.0.1 --port 8000 --ws-max-size 65536
```

Generate demo platform runners and run the web demo:

```bash
python3 scripts/bootstrap_flutter.py --platforms web
cd apps/flutter_client
flutter run -d chrome --web-port 8080
```

Open a second tab at the same URL. Connect the first as `door` and the second as `desk`, using their respective keys, then call. The demo's default URL is `ws://localhost:8000/ws`. This local profile has no TURN and only demonstrates local/direct connectivity; it does not validate Internet traversal. Two devices sharing a microphone/speaker can cause feedback: use headphones and separate physical devices for meaningful media tests.

## Docker deployment behind your Nginx

See [installation](docs/installation.md) before starting: edit domain names, install certificates, set file ownership and configure the Nginx `stream` module.

Split deployment:

```bash
docker compose up --build -d
```

Single-container deployment (FastAPI + coturn; your existing Nginx stays outside):

```bash
docker compose -f compose.all-in-one.yaml up --build -d
```

Experimental TCP-443-only split deployment:

```bash
docker compose -f compose.yaml -f compose.443.yaml up --build -d
```

Experimental TCP-443-only single-container deployment:

```bash
docker compose -f compose.all-in-one.yaml -f compose.all-in-one.443.yaml up --build -d
```

The overrides require Docker Compose **2.24.4+**. They replace the published port lists, removing the public UDP mappings. **Do not start the standard profile and assume that only TCP 443 is exposed.** Verify the resulting configuration with `docker compose ... config` before deployment.

## Important boundaries

- One signaling process, one active connection per device, one call per device. No multi-worker or horizontally scaled signaling yet.
- Ring timeout: 30 seconds; media setup timeout: 45 seconds; maximum active call: one hour.
- No background push notifications, screen sharing, recording, SIP gateway, group calls or automatic ICE restart yet.
- Device keys are long-lived, randomly generated credentials; the server stores their SHA-256 hashes. TURN credentials expire after two hours and are refreshed before each accepted call.
- Device provisioning and key rotation are operator actions. Restart signaling after changing device configuration; existing calls will be interrupted.
- HTTPS/WSS protects signaling; WebRTC encrypts media between peers. This release has no independent peer-identity verification against a compromised signaling server.
- TURN/TLS on TCP 443 is **not HTTPS**. A strict HTTP-only proxy may reject it.
- Shared-port SNI routing and same-server internal TURN relaying are **experimental until validated on every supported runtime and the target network**.

## Tests and CI

```bash
cd server
python -m pytest -q
```

GitHub Actions is configured to run server tests, Flutter analysis/widget tests/web compilation, and container health smoke tests for both layouts. Container health does not prove that a real video call works. See [testing](docs/testing.md).

## License

Original sonnetteKit code is MIT licensed. Bundled/dependent components retain their respective licenses; see [third-party notes](THIRD_PARTY.md).
