# Initial validation record

## Completed locally

- Python 3.13: 24 server/security/WebSocket tests passed locally, including
  dynamic sessions, multiple operator tabs and authoritative call audit.
- Flutter 3.29 / Dart 3.7: package dependency resolution, static analysis and
  all 3 widget tests passed locally.
- The consuming EntryMonitor Android debug APK and Profil UI Web debug bundle
  both compiled with `sonnette_kit` 0.2.0 and `flutter_webrtc` 1.6.2+hotfix.4.
- All Python source files parse; Compose and Flutter manifest YAML files parse.
- Tests cover authentication, invalid credentials and origins, duplicate device connections, invitation replay, call lifecycle, access controls, crossed invitations, timeouts, disconnect cleanup, malformed messages and temporary TURN credentials.

## Completed on GitHub Actions

[Initial CI run](https://github.com/Ergul/sonnetteKit/actions/runs/38149137834), commit `ce086a6e377d855ca6373b308cdcefe3c71a1195`:

- Server tests: passed.
- Flutter package analysis: passed.
- Flutter widget tests: passed.
- Flutter demo analysis: passed.
- Flutter Web production compilation: passed.
- Split Docker image build and service health smoke test: passed.
- Single-container image build and service health smoke test: passed.

A subsequent lifecycle guard allows shutdown before renderer initialization and adds a regression test. Check the latest commit's [CI status](https://github.com/Ergul/sonnetteKit/actions) for that change.

The current dynamic-session changes were validated locally as described above.
Docker and physical-device media were not exercised by that validation run.

## Not yet validated

- Native Android, Windows and macOS compilation and hardware behavior.
- Nginx configuration on the target host.
- End-to-end audio/video between physical devices.
- Shared-port SNI behavior across WebRTC runtimes and the experimental 443-only TURN topology.

Container health is not a substitute for a real call. Complete [the test plan](testing.md) before production deployment.
