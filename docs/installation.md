# Choose your platform

## Download

Open this repository's **Releases** page and download one asset:

- **workflow-hooks-kit-0.1.0.zip**: the complete kit, installer, local learning tools and documentation.
- **workflow-hooks-kit.plugin**: the account plugin for a Claude host that supports plugin uploads.

The ZIP contains no user data. Unzip it, open a terminal in its folder, and choose one command below. Python 3.9+ is required on macOS or Linux.

## Codex

```sh
python3 install.py --platform codex
```

Open Codex's native `/hooks` review and approve the installed hook definitions. Start a new task with a specific project folder. The installer does not manufacture trust approval. Follow the verification procedure below.

## Claude Code

```sh
python3 install.py --platform claude
```

Start a fresh local Claude Code session with a project folder. Existing unrelated hooks are retained. Project or managed settings may override global configuration; inspect those settings if the workflow is absent.

## Claude account plugin / Cowork

In a supported Claude desktop version, open **Customize > Plugins**, choose the plugin upload option, and select **workflow-hooks-kit.plugin**. Review its permissions and start a new agent task with an intended working folder. Account/plugin availability and Code synchronization depend on the host version. Ordinary chat does not gain executable hooks merely by loading written instructions.

Do not install another copy with a different version. An exact matching global install and this plugin deduplicate processing; mismatched versions are not silently skipped. Hosted standards remain local to their execution environment and do not automatically synchronize with your computer.

## Both local hosts

```sh
python3 install.py --platform both
```

Then perform each host's native trust/reload steps separately. A failure during a two-host install can leave the first host installed; the command reports which host completed. Do not interpret a saved JSON configuration as runtime proof.

## Small activation check

Use a disposable project with one `probe.txt` output. Ask the agent to attempt native Write without a plan: the hook should deny it and explain the `workflow-ledger plan` sentinel. Then ask it to prepare the compact plan, write the file, read its exact content and record QA. An incomplete Stop should request one correction. If any step is absent, report the missing event instead of bypassing trust or declaring success.

`workflow-ledger` is not a terminal program: only use it inside a supported native Bash tool call. See [working JSON examples](workflow.md). These checks consume ordinary host subscription usage; the local hook scripts themselves make no model/API requests.

## Remove

```sh
python3 install.py --platform codex --uninstall
python3 install.py --platform claude --uninstall
```

Remove an uploaded account plugin through that host's plugin settings separately. Local uninstall preserves changed/unrelated configuration, local data and backups. It does not remove an independently uploaded plugin.

## Optional shared local learning broker

The default install and release plugin leave MCP disabled. For explicit local
registration, use Python 3.11+ and a shared private store:

```sh
python3.11 install.py --platform both --learning-mcp \
  --state-dir /absolute/private/shared-learning \
  --policy-root /absolute/private/policies
```

The policy directory is optional and must already exist. Both local hosts use
that same state path. No model/API/network call is made by installation or the
broker. Local client registration does not activate a Cowork account plugin,
and does not prove automatic tool invocation. Generic native runtime coverage
is pending. See [broker configuration and limitations](../learning/MCP.md).
Ordinary uninstall also removes unchanged installer-owned MCP definitions;
modified or unrelated definitions, policy, learning state and backups survive.
