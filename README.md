# Workflow Hooks Kit

> Native-file hygiene preview: [customer status](https://github.com/omerm-AI/workflow-hooks-kit/blob/cd2712fa9511fd3f7059609570706868f0e5f9f2/docs/hygiene-customer-status.md), [installation guide](https://github.com/omerm-AI/workflow-hooks-kit/blob/cd2712fa9511fd3f7059609570706868f0e5f9f2/docs/customer-install.md), [Codex install prompt](https://github.com/omerm-AI/workflow-hooks-kit/blob/cd2712fa9511fd3f7059609570706868f0e5f9f2/prompts/install-hygiene-codex.he.txt), and [Claude Code install prompt](https://github.com/omerm-AI/workflow-hooks-kit/blob/cd2712fa9511fd3f7059609570706868f0e5f9f2/prompts/install-hygiene-claude-code.he.txt). Use immutable `hygiene-file-tools-preview-2026-10-20`, not this base branch, for the selected mode. Known native save/Stop gates passed independent operator-account tests and are activated on Codex and Claude Code. Shell/connector writes remain uncovered; existing processes must already have registered callbacks or reload and prove adoption. Installation does not reorganize historical files. Fresh-customer native canaries remain required. See [measured acceptance and retained limitations](https://github.com/omerm-AI/workflow-hooks-kit/blob/cd2712fa9511fd3f7059609570706868f0e5f9f2/docs/acceptance/2026-10-20-file-tools.md).

Version 0.1.0. Portable local planning, scope and verification checkpoints for Codex and Claude Code. Python 3.9+ on macOS/Linux; no third-party Python dependencies, model calls or installer network access.

## Customer bootstrap prompts

Start with the [step-by-step customer guide](docs/customer-install.md), or give your agent the [Codex install prompt](prompts/install-hygiene-codex.he.txt) / [Claude Code install prompt](prompts/install-hygiene-claude-code.he.txt). These install the reviewed opt-in preview rather than relying on memory. Installation does not retroactively reorganize projects; protection applies to future covered work in new or existing folders. The selected file-tools preview gates known native saves; shell/connector writes remain explicitly uncovered. Read the mode limits before activation.

The newer consent-based organization and contextual folder-guide component is published separately as [Project Hygiene Kit](https://github.com/omerm-AI/project-hygiene-kit). Read its current [acceptance status](https://github.com/omerm-AI/project-hygiene-kit/blob/main/docs/acceptance.md): its first native upgrade trials exposed an advisory-policy conflict, so the upgrade remains a preview and is not approved for persistent activation. Earlier base-kit proof does not prove the new component or override local warning-only policy.

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

Review and trust new Codex hooks through its native `/hooks` interface. Restart/reload the relevant host as needed. Configuration does not prove runtime activation. Windows is not supported by this POSIX implementation. Optional Codex MCP TOML registration requires Python 3.11+; default hooks retain Python 3.9+ support. These event schemas and host support may vary by release. This public release is verified through local native-event protocol replays, not a fresh end-to-end desktop execution on every host build. Neither installer modifies project instructions automatically. Optionally reference `rules/AGENTS.md` in your project policy.

```sh
python3 install.py --platform both --uninstall
```

Uninstall removes only unchanged exact hook objects and optional MCP definitions recorded as owned by this installer. It preserves unrelated hooks and later edits, and retains runtime, ledgers and timestamped configuration backups for recovery. It does not restore an old complete settings file over later changes. To recover a specific configuration, inspect the relevant `workflow-hooks-kit/backups/` file and merge the desired entries manually. If another installation already supplied an identical hook, this installation does not claim ownership.

## Claude plugin alternative

The source plugin is `claude-plugin/workflow-hooks-kit/`. Use your host's supported plugin loading interface. Build a deterministic ZIP artifact with:

```sh
python3 tools/build_plugin.py
```

This creates `dist/workflow-hooks-kit.plugin` with the manifest at `.claude-plugin/plugin.json` and the canonical learning CLI, stdio broker and their documentation under `learning/`; tests and state are excluded. Default builds have no MCP definition. An operator can explicitly build a private MCP-enabled plugin; see [MCP setup](learning/MCP.md). The plugin declares SessionStart plus the four workflow events and exposes `workflow-hooks-kit:work-standards`. SessionStart is a lightweight no-op. When matching global hooks and byte-identical runtime cores are present, the plugin skips duplicate processing. Keep global/plugin versions aligned; mismatched installations deliberately do not deduplicate. Some hosts may require a plugin directory or marketplace rather than a `.plugin` ZIP; packaging alone does not guarantee import support. Cowork requires an account and environment that actually support loading this plugin and its hooks. Uploading the ZIP to ordinary chat does not activate hooks. Consult [Claude plugin platform support](https://claude.com/docs/plugins/platform-support), [Claude Code hooks](https://code.claude.com/docs/en/hooks), and [Codex hooks](https://learn.chatgpt.com/docs/hooks) for current host capabilities.

## Use

See [the workflow contract](docs/workflow.md) for compact and substantial JSON examples. `workflow-ledger` is a hook-intercepted sentinel within native Bash tool calls, not a terminal executable. A saved-plan denial is expected. Conversation gets no additional workflow context; material prompt context is capped at 300 characters.

Ten mechanisms are explained in [coverage](docs/coverage.md). Hooks validate local declarations and recognized tool boundaries; they cannot prove actual reviewer/model identity or every shell side effect. Generic MCP writes remain unchecked. Stop blocks at most once per ledger and then reports remaining issues; escaping a Stop block is never a success certificate.

## Optional event evidence and language

[Local signed receipts](docs/hook-receipts.md) bind a one-use marker to hashed event identities, time and installed runtime version. They do not authenticate native origin by themselves. [The optional response-language hook](docs/response-language.md) includes a controlled native Code Local enabled/disabled sample with matching static instructions excluded. That sample does not establish every future response, Cowork, Codex or ordinary GPT behavior. Install language support explicitly with `python3 tools/configure_language.py --language he` (or `en`); it adds bounded bootstrap context, then no language context on cached prompts. The base installer does not enable this optional hook.

[The native Agent observer](docs/delegation-observer.md) records bounded requested/resolved model metadata with a signed data-bound marker. Its controlled Code Local pilot observed an actual worker, but does not enforce model selection or certify parent QA. It is not automatically registered by the base installer.

## Privacy and optional integrations

The runtime reads incoming hook JSON, recognized tool inputs, the kit's local state, configuration for plugin deduplication, and narrowly declared local file assertions. It does not collect transcripts, access credentials, call models or send data over a network. Ledgers contain local session/turn identifiers, project paths, declared plans and QA text; do not put secrets in those declarations. Input text is used transiently for classification and is not retained. Runtime failures are generally fail-open, so this is a workflow aid rather than a security sandbox.

The optional [learning CLI](learning/) processes explicitly supplied local material and approved scoped standards. Agents can load a relevant generated standard on demand through the CLI approval validation; there is no automatic transcript scanning or live cloud synchronization. Total Recall is optional, separately installed and not bundled. This kit neither installs recall nor invokes paid APIs. An opt-in [local stdio broker](learning/MCP.md) can expose a shared host-local state directory and an operator policy root. Installation does not automatically invoke MCP tools before prompts. Generic native coverage across old/new desktop, Code and Cowork sessions remains pending. Model cost selection and model scheduling remain agent policy decisions.

## Verify locally

```sh
python3 -B -m unittest discover -s tests -v
```

Tests use temporary homes under your home directory (the core intentionally rejects `/tmp` as a project root), preserve unrelated settings, and never touch live host configuration. For learning tests, run the documented command in that module. No binary artifact needs to be tracked in Git.

[The stage request validator](docs/delegation-binding.md) mechanically binds a canonical DoD packet and requested model to a frozen stage. It is not yet connected to a native enforcement handler. A separate native input-rewrite sample establishes a possible delivery path, without certifying full routing or QA enforcement.

## Native-file hygiene preview

The customer guide selects `--hygiene-file-tools`: known native saves and Stop are gated while ordinary shell/connector writes remain Open. The separate strict `--hygiene-enforcement` option adds supported-file preflight, verified prior-byte backups, post-edit review gates and conservative reversible transfers. Native guard tests have observed Write/patch then Stop blocks in disconnected fresh/existing project fixtures. This does **not** certify universal customer rollout or interception of every native/MCP/shell path. Strict mode rejects unverified shell writes and may prevent ordinary builds. Read [the contract and limits](docs/hygiene-enforcement.md) and [acceptance evidence](docs/acceptance/2026-10-20-hygiene.md) before opting in. Existing installations are not silently enabled.

See the [current customer summary](docs/hygiene-customer-status.md) and [limited-mode acceptance](docs/acceptance/2026-10-20-file-tools.md) for cleanup demonstrations, installation and existing-folder/session limits.
