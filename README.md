# Workflow Hooks Kit

Version 0.1.0. Portable local planning, scope and verification checkpoints for Codex and Claude Code. Python 3.9+ on macOS/Linux; no third-party Python dependencies, model calls or installer network access.

## Install

Start with [platform-specific download and installation steps](docs/installation.md).

From a downloaded clone:

```sh
python3 install.py --platform both
# Or choose --platform codex / --platform claude.
# A sandbox install never activates your real account:
python3 install.py --platform both --home "$HOME/workflow-sandbox"
```

Codex configuration is merged into `~/.codex/hooks.json`; Claude global configuration into `~/.claude/settings.json`. Each receives UserPromptSubmit, PreToolUse, PostToolUse and Stop. Existing unrelated settings remain. Reinstall is idempotent. `--platform both` processes hosts sequentially; an error reports completed hosts and is not a transaction across both configurations. Runtime files live in the host's `workflow-hooks-kit/bin/`; local JSON ledgers are stored separately per host. Installed base standards are in `WORK_STANDARDS.md`; optional learning is `bin/learning_cli.py` with `LEARNING.md` instructions. Use that installed path instead of `learning/cli.py` in the module examples.

Review and trust new Codex hooks through its native `/hooks` interface. Restart/reload the relevant host as needed. Configuration does not prove runtime activation. Windows is not supported by this POSIX implementation. These event schemas and host support may vary by release. This public release is verified through local native-event protocol replays, not a fresh end-to-end desktop execution on every host build. Neither installer modifies project instructions automatically. Optionally reference `rules/AGENTS.md` in your project policy.

```sh
python3 install.py --platform both --uninstall
```

Uninstall removes only unchanged exact hook objects recorded as owned by this installer. It preserves unrelated hooks and later edits, and retains runtime, ledgers and timestamped configuration backups for recovery. It does not restore an old complete settings file over later changes. To recover a specific configuration, inspect the relevant `workflow-hooks-kit/backups/` file and merge the desired entries manually. If another installation already supplied an identical hook, this installation does not claim ownership.

## Claude plugin alternative

The source plugin is `claude-plugin/workflow-hooks-kit/`. Use your host's supported plugin loading interface. Build a deterministic ZIP artifact with:

```sh
python3 tools/build_plugin.py
```

This creates `dist/workflow-hooks-kit.plugin` with the manifest at `.claude-plugin/plugin.json` and only the canonical learning CLI and README under `learning/`; tests and state are excluded. The plugin declares SessionStart plus the four workflow events and exposes `workflow-hooks-kit:work-standards`. SessionStart is a lightweight no-op. When matching global hooks and byte-identical runtime cores are present, the plugin skips duplicate processing. Keep global/plugin versions aligned; mismatched installations deliberately do not deduplicate. Some hosts may require a plugin directory or marketplace rather than a `.plugin` ZIP; packaging alone does not guarantee import support. Cowork requires an account and environment that actually support loading this plugin and its hooks. Uploading the ZIP to ordinary chat does not activate hooks. Consult [Claude plugin platform support](https://claude.com/docs/plugins/platform-support), [Claude Code hooks](https://code.claude.com/docs/en/hooks), and [Codex hooks](https://learn.chatgpt.com/docs/hooks) for current host capabilities.

## Use

See [the workflow contract](docs/workflow.md) for compact and substantial JSON examples. `workflow-ledger` is a hook-intercepted sentinel within native Bash tool calls, not a terminal executable. A saved-plan denial is expected. Conversation gets no additional workflow context; material prompt context is capped at 300 characters.

Ten mechanisms are explained in [coverage](docs/coverage.md). Hooks validate local declarations and recognized tool boundaries; they cannot prove actual reviewer/model identity or every shell side effect. Generic MCP writes remain unchecked. Stop blocks at most once per ledger and then reports remaining issues; escaping a Stop block is never a success certificate.

## Privacy and optional integrations

The runtime reads incoming hook JSON, recognized tool inputs, the kit's local state, configuration for plugin deduplication, and narrowly declared local file assertions. It does not collect transcripts, access credentials, call models or send data over a network. Ledgers contain local session/turn identifiers, project paths, declared plans and QA text; do not put secrets in those declarations. Input text is used transiently for classification and is not retained. Runtime failures are generally fail-open, so this is a workflow aid rather than a security sandbox.

The optional [learning CLI](learning/) processes explicitly supplied local material and approved scoped standards. Agents can load a relevant generated standard on demand through the CLI approval validation; there is no automatic transcript scanning or live cloud synchronization. Total Recall is optional, separately installed and not bundled. This kit neither installs recall nor invokes paid APIs. Model cost selection and model scheduling remain agent policy decisions.

## Verify locally

```sh
python3 -B -m unittest discover -s tests -v
```

Tests use temporary homes under your home directory (the core intentionally rejects `/tmp` as a project root), preserve unrelated settings, and never touch live host configuration. For learning tests, run the documented command in that module. No binary artifact needs to be tracked in Git.
