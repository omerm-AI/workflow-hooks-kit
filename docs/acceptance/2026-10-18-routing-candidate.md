# Native routing candidate: bounded acceptance run

This candidate is **not installed globally** and is not an accepted universal routing solution. The run permits at most three repair iterations; previous unsuccessful candidates remain archived. Subscription-native clients are used without model API keys. Production hook scripts make no model requests.

## Implemented boundary

`routing_policy.py` selects the lowest operator-configured rank satisfying a declared capability profile. Capability adequacy and rank are explicit planner/operator inputs, not independently measured prices or proof of model competence. Stages use `worker_model: auto:<profile>` within the existing frozen-plan schema.

`routing_guard.py` is an experimental Claude Code sidecar. A native prompt checkpoint records identity and policy binding. Before an Agent call, it checks the real workflow core, rewrites the native request with the chosen model and frozen numbered stage/DoD packet, and preserves ordinary permission review. PostToolUse correlates native identity, request, policy, runtime and reported resolved model. A matching model observation does not prove semantic QA or successful completion of the whole workflow.

Only an exact first-line `WORKFLOW_MODEL=<alias>` currently identifies a human override. Natural-language explicit model requests are not supported, so the original user-override requirement remains **Open**. Nested delegation and overlapping dispatch are intentionally restricted in this candidate. These limitations prevent a global deployment claim.

## Measured native observations

Claude Code candidate 2 used empty user instruction-file inventories, no skills or MCP servers, and a neutral request to delegate a literal response. The parent request passed the observational isolation preflight. The actual PreToolUse hook emitted `updatedInput` containing the canonical stage packet, Haiku alias and low effort. Native execution started a worker.

The diagnostic observer then rejected the worker's canonical packet because its allowlist covered only the neutral parent prompt. No worker model request was forwarded by that observer. There is no completion proof for that attempt, and the OFF arm was skipped to avoid unnecessary inference. Candidate 3 permits only the exact frozen worker packet in addition to the neutral parent request.

The disposable test checkpoint prepares its input plan through the actual core plan API using native event identities. This is fixture setup: it does not demonstrate that the production parent independently plans every task. No generated private records, machine paths, account details, raw prompts or credentials are included here.

## Acceptance still required

- Production-installed native completion and independent QA across ordinary tasks; the narrower prepared-fixture ON check passed.
- Hook ON/OFF attribution for the claimed selection outcome.
- Explicit natural-language model override without overriding other controls.
- Codex native dispatch interception and actual worker model binding.
- Global registration, trust review where required, deduplication and fresh installed-session tests.

Until those checks pass, the broad routing/delegation rows remain **Open**. Saving configuration and passing local tests are not substitutes for those checks.

## Candidate 3 observed result

The ON arm completed the prepared-fixture route. The parent and worker observation steps passed the diagnostic allowlist. The observer recorded one context/system inventory, reused across both steps; it did not independently enumerate a second worker context. Native PreToolUse supplied the exact canonical packet, `haiku` model alias and `low` effort. The worker returned exactly `13`; native PostToolUse reported `completed`, resolved `claude-haiku-5-5` and a matching local signed observation. The original user/project instruction-file inventory was empty; built-in vendor instructions remained. The fixture and observational plugin were test-only.

The OFF parent also passed preflight and attempted an ordinary Agent request without the canonical packet. Its worker was stopped by the same diagnostic allowlist, which deliberately permits only the exact canonical test packet in addition to the neutral parent request. Consequently this is **not** a successful two-arm comparison of model cost or task success. It does not show that an unhooked model would choose a more expensive worker. No fourth repair iteration is authorized in this run.

The narrow ON dispatch/model/exact-output check is **Tested and proven**; universal routing and the full counterfactual remain **Open**. Local ranks do not measure subscription quota savings. All generated artifacts stay private.

## Independent review and Codex prelaunch limitation

An independent Astra review verified the ON context, pending binding, result and receipt signatures, current code/policy stamps, session/prompt/tool correlation, resolved worker model, agent hash and exact literal output. This approves the stated ON fixture scope only.

The Codex probe did not reach native events: its command exited 2 before a session, dispatch or hook receipt was observed. Its reported arguments included `--ask-for-approval` after `exec`; a separate help/parser-only check reproduces rejection of that unsupported subcommand argument without inference. Original stderr was not retained, so the original error text is not independently recoverable. This is a test-runner failure, not proof that a Codex hook passed or failed. No further native retry was performed after the three-iteration limit.

Project hygiene: active source, generated acceptance evidence and failed-attempt diagnostics are retained because independent comparison and rollback analysis still require them. No private runtime artifacts are included in the Git change.
