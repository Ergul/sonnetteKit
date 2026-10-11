# Initial validation record

## Completed locally

- Python 3.12: 17 server/security/WebSocket tests passed.
- Tests cover successful authentication, invalid credentials and origins, duplicate device connections, invitation replay, call lifecycle, access controls, crossed invitations, timeouts, disconnection cleanup, malformed messages and temporary TURN credentials.

## Not yet validated

- Flutter analysis, widget tests and Web compilation: local Flutter SDK initialization was blocked by the execution environment's automatic review after an attempted cloud-metadata request. No successful Flutter build is claimed. CI provides the compilation/test gate on GitHub-hosted runners.
- Docker image builds/startup: Docker is unavailable in the authoring environment. CI provides a health smoke test for both layouts.
- Native Android, Windows and macOS compilation and hardware behavior.
- Nginx configuration on the target host.
- End-to-end audio/video and the experimental 443-only TURN topology.

See the GitHub Actions run for the exact published commit before using the initial version. This record describes local evidence, not the eventual status of CI.
