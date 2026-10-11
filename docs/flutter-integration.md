# Embed sonnetteKit in your Flutter application

## Public API

`SonnetteClient` is a `ChangeNotifier`. It owns the signaling socket, WebRTC peer connection, local/remote streams and renderers. Keep one instance per signed-in device session. `SonnetteCallWidget` listens to it; disposing the widget does not disconnect the client.

The controller provides:

- `connect(server: ..., id: ..., token: ...)`
- `invite(target)`, `accept()`, `reject()`, `hangUp()`
- `setMicrophone(enabled)`, `setCamera(enabled)`
- `disconnect()`, `shutdown()`, then synchronous `dispose()`
- `online`, `phase`, `callId`, `peer`, `peers`, `error`, `mediaStatus`
- `localRenderer`, `remoteRenderer` for custom UIs

The widget accepts `client`, optional `targetDeviceId`, `title` and `onError`. It needs Material ancestors and bounded height, e.g. `Expanded` or `SizedBox(height: 620)`. It follows the host theme. Labels are initially English; localization is not implemented yet.

Connect on a user action or in an async application/session initialization flow, never in `build()`. Hold the controller in your app's existing state-management layer. You can embed the widget on a page, in a dialog, or in a side panel; in a dialog, choose a bounded width/height. To customize the incoming-call notification globally, observe `phase == CallPhase.incoming` from your app and show your own UI.

## Credentials

Pass device-specific keys from your host application's provisioning flow. The package keeps the key only in memory. The demo's form is for testing, not a production login experience. Do not compile live keys into a Flutter Web bundle, commit them, place them in URLs, or use the same key for all devices. Host applications need an appropriate secure provisioning/storage strategy.

## Platforms

The intended targets are Android, Web, Windows and macOS. Compilation and hardware behavior must be verified for each release and platform. The package uses `flutter_webrtc`; platform setup is still the host application's responsibility.

- **Web:** use HTTPS except on localhost. Grant microphone/camera permissions. Test Chrome, Edge and Safari separately; background tabs and audio autoplay policies can differ. The server must allow your exact Origin.
- **Android:** declare `INTERNET`, `CAMERA`, `RECORD_AUDIO`, `ACCESS_NETWORK_STATE`, `CHANGE_NETWORK_STATE`, `MODIFY_AUDIO_SETTINGS`. Verify runtime permission behavior, audio routes and release-build plugin requirements. Background calls/foreground services/notifications are out of scope for this first version. The demo bootstrap adds basic manifest declarations.
- **macOS:** add camera/microphone usage descriptions and sandbox entitlements for camera, audio input and outgoing network connections. The demo bootstrap adds these to generated runners.
- **Windows:** grant camera/microphone access in system settings and verify native plugin setup with your chosen Flutter toolchain.
- **iOS/Linux:** not part of the initial tested target matrix; no generated setup is provided by default.

## Demo runners

The repository keeps the integration demo source and a runner generator instead of committing machine-generated native project boilerplate before choosing your final app IDs and signing setup:

```bash
python3 scripts/bootstrap_flutter.py --platforms web,android,windows,macos
```

Run each native build on a supported host. The generator does not replace existing platform folders, `lib/` or `pubspec.yaml`; it does add basic permissions to generated Android/macOS runners. Review generated files before committing them. Bluetooth routing, background calling and app-store signing remain separate integration work.

## Lifecycle and failure behavior

- Camera and microphone are requested after the call is accepted, not when the widget is first displayed.
- A permission/media setup failure ends the call and surfaces an error.
- ICE candidates received before the remote SDP are buffered.
- Only the caller creates an offer; this release does not renegotiate or perform ICE restarts.
- Signaling disconnect ends the call and reconnects with backoff; the user must redial.
- A second connection with the same identity is rejected; it does not replace the first.
- The widget must not dispose a controller owned by another part of the app.
- Before the owner disposes a client, call `await client.shutdown()`; in synchronous Flutter `State.dispose`, schedule shutdown and call `client.dispose` when it completes, as shown in the demo.
