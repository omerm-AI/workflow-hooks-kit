# Security and privacy

The kit does not make model, API, telemetry or network calls. Installation changes only the selected platform's local hook configuration and the kit's owned runtime directory, with local backups. Native hooks can read bounded declared outputs for acceptance checks; this is local processing, not data upload.

Keep local hook journals, settings backups, learned preferences and model outcomes out of source control. Do not attach them to public issues. The shipped examples use synthetic data only. No transcripts, account settings, credentials, client information or original deployment evidence belong in this repository or a release asset.

Hooks are workflow checks, not an operating-system sandbox. Only the declared native tool matchers are covered. Arbitrary shell programs, remote tools, MCP servers and platform delivery bridges are not universally intercepted. Observer failures fail open and never mean acceptance passed. The learning approval flag records a caller declaration; it is not an authenticated human approval mechanism.

Review scripts before installation. Use native platform trust controls and a disposable project for activation testing. Never disable trust or managed security settings to make a test pass. This release supports Python 3.9+ on macOS and Linux; Windows is not currently supported.

If reporting a vulnerability, describe the behavior with synthetic reproduction steps. Do not publish real secrets, local paths identifying people, private content or a user's runtime journal.
