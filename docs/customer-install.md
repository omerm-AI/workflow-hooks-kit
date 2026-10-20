# Customer installation: strict project hygiene

This opt-in installs strict hygiene for Codex or Claude Code. The supported sequence uses two separate disposable homes: a model-free smoke home, then an installed native-canary home. Only after native evidence may the selected real account be installed. Python 3.9+ on macOS/Linux is required. Overall customer rollout remains **Open**; narrower results are **Tested and proven** only for their measured boundaries.

## 1. Clone and inspect the reviewed preview

```sh
git clone --branch hygiene-preview-2026-10-20 --depth 1 https://github.com/omerm-AI/workflow-hooks-kit.git workflow-hooks-kit-preview
cd workflow-hooks-kit-preview
git status --short
git rev-parse HEAD
git describe --tags --exact-match HEAD
```

Confirm the exact tag, inspect the commit and clean working tree, and read `README.md`, `install.py`, `docs/hygiene-enforcement.md`, `docs/hook-status.md`, and `docs/acceptance/2026-10-20-hygiene.md`. Review the installer's targets. Do not install from a fork, another branch, or a modified checkout.

Inspect the chosen account for an equivalent kit, plugin, custom hook core, or another runtime owning the same events. If there is a conflict, stop and report the exact paths and safe next step. Never duplicate, replace, uninstall, or silently merge a different local runtime.

## 2. Run the model-free smoke check

Choose exactly one platform. Pass an absolute path to a new home that does not yet exist; do not create the directory yourself. The smoke script creates it, checks configuration coexistence and idempotence, exercises the installed guard without model calls, then removes its temporary hook registration. This home is not the native-canary home.

```sh
python3 tools/hygiene_smoke.py --home /absolute/new/smoke-home --platform codex
# or
python3 tools/hygiene_smoke.py --home /absolute/new/smoke-home --platform claude
```

Keep the output. If the home already exists, the tool is missing, or the result fails or is unclear, stop before the native canary and report the blocker. A pass does not prove native hook activation.

## 3. Install a second disposable home for the native canary

Choose a different absolute path that also does not yet exist. Run the actual installer with strict mode enabled; do not reuse the smoke home:

```sh
python3 install.py --platform codex --home /absolute/new/codex-native-home --hygiene-enforcement
# or
python3 install.py --platform claude --home /absolute/new/claude-native-home --hygiene-enforcement
```

Inspect the installer result and the second home's settings/runtime. This changes only the disposable home. It merges hook settings, installs runtime files including `WORK_STANDARDS.md`, and creates the strict policy marker and recovery state. It does not alter project files. Confirm unrelated settings were retained before attempting the native canary.

## 4. Verify native trust and behavior before real installation

Use only the selected client's existing CLI/subscription authentication. Do not supply, copy, or fall back to API keys or credential files, and do not create a paid service. If the current CLI subscription is not available, pause before any native model call and report that login prerequisite.

For **Claude Code**, the staging canary is intended to load the second home's settings in restricted mode, while the client retains its existing subscription authentication. Installed commands explicitly bind only the hook subprocess HOME to the staging home:

```sh
cd /path/to/disposable-project
claude --restricted --settings /absolute/new/claude-native-home/.claude/settings.json
```

This invocation is an **Open** prerequisite until the current preview's installed hook commands are verified to honor the target `HOME` and an actual native canary produces matching callbacks and file behavior. Do not mark it passed from the command or config alone.

For **Codex**, the explicit `CODEX_HOME` profile below was checked without inference: the native server discovered all four hooks from the second home's `hooks.json`. The new profile was logged out and its hooks untrusted. Existing account credentials are not copied or silently reused:

```sh
CODEX_HOME=/absolute/new/codex-native-home/.codex codex login status
# If logged out, ask the user to finish the normal subscription login:
CODEX_HOME=/absolute/new/codex-native-home/.codex codex login
CODEX_HOME=/absolute/new/codex-native-home/.codex codex -C /path/to/disposable-project
```

Inside that profile, open `/hooks` and ask the user to trust the four reviewed definitions. Do not use API-key login, copy credential files, forge trust records or start inference while logged out/untrusted. Then run the controlled file canary. Profile discovery is **Tested and proven**; the fresh-profile native canary remains **Open** until login, trust and actual callbacks are evidenced. The operator's existing Codex account is a different profile and cannot substitute for this fresh-profile proof.

Check relevant managed and project-level settings for overrides. A fresh canary must observe the actual hook callback and file result. Do not assume already-open sessions adopt new settings; test that separately or report it **Open**. Do not proceed to the real account while the selected platform's native prerequisite remains **Open**.

## 5. Install into the selected real account

Strict mode rejects ordinary shell commands without a verified write boundary, including builds or generators that may write files. Disclose this effect and the evidence scope before installation. An explicit request to install authorizes this opt-in; do not add another approval step when that request is clear.

After the smoke check, second-home install, and native canary pass for the selected client, run only that platform's command:

```sh
python3 install.py --platform codex --hygiene-enforcement
# or
python3 install.py --platform claude --hygiene-enforcement
```

The installer changes the selected account's host settings, runtime, strict-policy marker, receipts/backups, and private local workflow state as applicable. Inspect reported paths and confirm unrelated settings remain intact. It does not edit existing project files, scan trees, or perform bulk cleanup. Existing projects are considered only during later work when covered calls reach the installed hooks; there is no retroactive cleanup. Test whether already-open sessions adopt the settings.

## 6. Make the policy available during later work

The installer places `WORK_STANDARDS.md` in the host's kit directory (`~/.codex/workflow-hooks-kit/` or `~/.claude/workflow-hooks-kit/`). It does not add project `AGENTS.md`/`CLAUDE.md` instructions or automatically load the repository's `rules/HYGIENE-CODEX.md` / `rules/HYGIENE-CLAUDE.md`. For later material file tasks, explicitly direct the agent to read the installed `WORK_STANDARDS.md` and the selected hygiene contract, or add a reviewed reference to the intended project's instructions. Do not rely on memory or imply that these files were auto-attached.

The native hooks provide executable gates for supported events. When a covered tool call is denied, the returned hook message gives the model the next ledger or hygiene sentinel needed to continue. That callback behavior does not make written instructions universal, and it applies only when the host delivers the supported event.

## 7. Work within the supported boundary

Supported intercepted ledger sentinels are `workflow-ledger plan` and `workflow-ledger qa`. Supported hygiene sentinels are `workflow-hygiene inspect`, `workflow-hygiene read`, `workflow-hygiene review`, and `workflow-hygiene restore`. Send exact standalone commands through the native hooked shell tool; they are intercepted and are not ordinary shell programs. Use native known file tools for edits after review accepts the exact target. Do not bypass denials through aliases, another shell, connectors, or unreviewed tools.

Before editing an existing file, preserve it in a unique folder under that project's `Old/YYYY-MM/`, retaining its relative path and verifying the archive hash. A new file has no previous version to back up. Finish post-edit review and workflow QA before the next edit. Keep required source, tests, docs, configuration, dependencies, and helpers where the project requires them. Put other helpers in `Assets` with the recovery structure. Check local and declared external dependencies and concurrent work before moving anything. Archive only a reviewed byte-identical supported media/document duplicate with a distinct canonical copy and no detected local literal references. If uncertain, retain it and ask the operator. Never permanently delete history, automatically edit unrelated folders, or infer disuse from age or name.

The guard cannot cover unknown MCP/connector effects, external editors, other machines, native paths that do not send supported events, every dynamic/external reference, same-account tampering, or host Stop limits. Bounded scans and review notes do not prove semantic correctness. Never claim universal enforcement or 100% safety. Uninstall retains runtime state and backups for recovery; review them before reinstalling.

## 8. Report evidence

Report the tested preview commit, smoke output, second-home installer result, native trust/canary evidence, whether the real account was installed, and any untested boundaries. Use **Tested and proven** only for measured outcomes and **Open** for unresolved ones. Global adoption across projects, sessions, and tool paths remains **Open**.

See [strict hygiene contract and limits](hygiene-enforcement.md), [binary hook acceptance status](hook-status.md), and [native hygiene acceptance](acceptance/2026-10-20-hygiene.md).

## Measured first-time installation

The immutable preview was cloned over public HTTPS into a fresh checkout and its commit matched the remote tag. All four installed-command smoke cases passed without model calls. Claude Code then executed the unchanged recorded installer command in a fresh staging home, denied an actual unreviewed Write and emitted matching source-bound native receipts using one subscription request. A disclosed test-only UPS prepared the baseline plan but supplied no hygiene review. Codex fresh-profile discovery passed; login/trust remain prerequisites for its native test. See [first-install record](acceptance/2026-10-20-first-install.md).
