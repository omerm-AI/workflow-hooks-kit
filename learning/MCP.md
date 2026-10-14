# Experimental local learning broker

`mcp_server.py` exposes the existing CLI store through a standard-library-only,
newline JSON-RPC stdio service. It makes no network or model calls. Runtime files are bundled adjacent to `cli.py`. Registration is opt-in;
the default installer and plugin do not enable MCP.

```sh
python3 learning/mcp_server.py --state-dir /absolute/private/learning
```

Tools are `prompt_checkpoint`, `read_scoped_policy`, `propose_rule`, and
`learning_status`. Proposals remain pending; none of these tools approves a
rule. Caller metadata and approval declarations are not identity authentication.

An operator can supply `--policy-root /absolute/private/policies` to read an
existing canonical policy directory. The fixed read allowlist is `ROUTER.md`
and `references/{execution,quality,efficiency,continuity,visual,writing,
automation,security,workshops,proposals,brain}.md`. Symlinks and oversized files
are refused. This API allowlist does not sandbox the operating-system process:
a local MCP process still runs with its user's permissions.

`prompt_checkpoint` returns valid hook JSON when `as_hook` is true. Ordinary
conversation returns `{}`; a recognized work prompt can return a short pointer
to scoped rules. This heuristic is not a security classification. Supplied
agent or scheduled markers exempt capture. A narrow explicit remember request
can create a pending hypothesis, never an active standard.

Receipts retain hashed session and turn identifiers and policy fingerprints,
not prompts or paths. Older receipt metadata is archived before the bounded
active index is replaced. A receipt proves a broker call only: native tests
must establish that the client invoked it before the model, used the correct
session identifiers, and connected to the intended host-local store.

Native automatic invocation across old and new desktop, hosted, and Code
sessions is not yet verified. Do not interpret protocol or unit tests as that
proof. Classic chat, offline operation, managed restrictions, plugin refresh,
and unavailable connectors require separate runtime evidence. Weekly ingestion
into another preference framework is not implemented by this broker.

Run broker tests with `python3 -B -m unittest discover -s tests -v`, and CLI
tests with `python3 -B -m unittest discover -s learning -p 'test*.py' -v`.

## Optional local registration

The default install keeps MCP disabled. To register the broker explicitly:

```sh
python3.11 install.py --platform both --learning-mcp \
  --state-dir /absolute/private/shared-learning \
  --policy-root /absolute/private/policies
```

`--policy-root` is optional and must name an existing operator directory.
Both clients must use the same absolute `--state-dir` for a host-local shared
store. Its default is `<selected-home>/.local/share/workflow-hooks-kit/learning`.
No private policy or state files are bundled. Basic hooks support Python 3.9+;
optional Codex TOML registration needs Python 3.11+ for standard-library parsing.
Claude registration uses the installer interpreter as its launcher.

Codex receives `[mcp_servers.workflow_learning]` in `~/.codex/config.toml`.
Claude Code receives `mcpServers.workflow_learning` in `~/.claude.json`.
These are local client definitions, not proof of invocation or Cowork access.
Existing names are never overwritten or claimed. Exact installer-owned entries
can be reinstalled and uninstalled; later edits are preserved. Backups and
ownership receipts remain under each host's installed kit. A failed multi-host
install may leave the first host configured. MCP and hook file edits are not
one atomic transaction; inspect the reported error before retrying.

For an operator-local account plugin, build an explicitly configured artifact:

```sh
python3 tools/build_plugin.py --output /private/output/learning.plugin \
  --learning-mcp --state-dir /absolute/private/shared-learning \
  --policy-root /absolute/private/policies
```

This adds the documented plugin `.mcp.json` definition with
`${CLAUDE_PLUGIN_ROOT}/learning/mcp_server.py`. Upload/review through the host's
native plugin interface separately. Do not publish an operator-configured
artifact containing private paths; the default release artifact has no MCP
configuration. Cowork support depends on the host's plugin MCP transport and
where it executes; a hosted process cannot assume access to local files.

Native runtime coverage remains pending for the generic kit. MCP registration
does not add a pre-prompt hook and does not automatically call tools, models,
APIs, or networks. It does not synchronize policy across machines. Test each
intended host and existing/new session before claiming coverage.

Configuration references: [Codex MCP](https://developers.openai.com/codex/mcp),
[Claude Code MCP](https://code.claude.com/docs/en/mcp), and
[Claude plugin MCP](https://code.claude.com/docs/en/plugins-reference#mcp-servers).
