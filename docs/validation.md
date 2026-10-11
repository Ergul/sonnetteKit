# Initial validation record

## Completed locally

- Python 3.12: 17 server/security/WebSocket tests passed.
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

Local Flutter SDK initialization was blocked by the authoring environment's automatic review after an attempted cloud-metadata request. No local Flutter build is claimed; the successful Flutter checks above ran on GitHub-hosted runners. Docker was also unavailable locally.

## Not yet validated

- Native Android, Windows and macOS compilation and hardware behavior.
- Nginx configuration on the target host.
- End-to-end audio/video between physical devices.
- Shared-port SNI behavior across WebRTC runtimes and the experimental 443-only TURN topology.

Container health is not a substitute for a real call. Complete [the test plan](testing.md) before production deployment.
