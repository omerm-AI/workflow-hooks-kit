# Experimental local learning broker

`mcp_server.py` exposes the existing CLI store through a standard-library-only,
newline JSON-RPC stdio service. It makes no network or model calls. It is not
installed or enabled by the current kit installer or release package.

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
