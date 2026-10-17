# Strict enforcement: contract and current gaps

**Not implemented as a universal guarantee.** This document defines acceptance targets, not a new runtime feature or a successful deployment. The existing kit cannot prove mandatory model selection, actual worker dispatch, or independent review from caller-supplied ledger fields.

## Required control flow

Every task must pass a routing decision before execution: task scope, available capabilities, chosen model and worker, rationale, and acceptance checks. A classifier may reduce bookkeeping but must not waive the decision. Explicit human insistence on a particular model overrides model selection only, not permissions, scope, checks, or other rules. Text merely mentioning a model is insufficient evidence of that choice. Use existing native human-message provenance where available; otherwise mark authorization unverified.

For delegated work, prepare numbered stages, inputs, boundaries, dependencies, outputs, Definition of Done (DoD), and checks with expected results before dispatch. Select the cheapest adequate route using estimated total setup, context, execution, review, and retry cost; token tier alone is insufficient. Without reliable price or usage data, label cost estimates and do not claim measured savings. Avoid another model call merely to classify a trivial message.

The controller must verify native dispatch and completion events tied to the task and agent, plus independently checkable output artifacts. Worker/model/reviewer labels are declarations, not proof. Require a distinct observed reviewer for delegated stages. Freeze acceptance criteria before execution; version authorized changes and invalidate affected QA. A recorded judgment proves that a decision happened, not that it was correct.

Count meaningful failed attempts from observed stage results. Permit at most three attempts per available suitable capability tier; stop immediately on success or missing external prerequisites. Escalation requires an actual supported dispatch, not a changed label. After three failed attempts at the strongest suitable tier, return for human review. Never buy credits or invoke a paid model API to satisfy routing.

Absent activation, identity, required evidence, or interception must yield **blocked/unavailable**, never PASS. A one-continuation Stop budget controls cost; exhausting it does not complete the task. The native host may still terminate the turn. This kit cannot make all interfaces unavoidably obey a final-answer gate.

## Coverage and evidence matrix

| Mechanism | Required evidence | Existing limit |
|---|---|---|
| Model choice | Task-bound routing decision and observed supported dispatch; explicit human model override where applicable | Advisory/declared model names do not authenticate dispatch or backend identity |
| Preparation | Frozen DoD, numbered stages where needed, scoped outputs and acceptance checks | Prompt classifier can miss substantial work; small plans contain fewer fields |
| File scope | Pre-execution validation against the intended accessible project root | Recognized native edit tools only; arbitrary shell, connector and remote writes are not universally intercepted |
| Touched paths | Native edit/path events, including deletions where supplied | Shell execution alone does not identify all effects |
| Completion and QA | Fresh execution results tied to frozen checks, artifacts and independent reviewer where required | Ledger validates structure; free-text evidence and reviewer labels do not prove QA truth; literal assertions cover only bounded files |
| Project hygiene | Reviewed reversible move manifest, hashes, dependencies and recovery path | Human/model policy and reminders, not automatic dependency verification or archival |
| Delegation and retries | Native worker dispatch/completion and observed failed attempt counts | No authenticated scheduler or automatic escalation; submitted attempts are declarations |
| Preference learning | Scoped proposal, actual human approval and approved canonical lookup before use | Local CLI/broker support only; automatic capture and future consumption differ by host |
| Failure learning | Observed failure, scoped proposed lesson and approval before promotion | Records do not constitute calibrated model capability or complete telemetry |
| Recall | Actual integration query/result evidence | Separate integration; not a universal built-in service of this kit |
| Shared checkpoint | Matching native turn/session event and broker receipt; approved policy read evidence | Configuration/manual connector success does not prove automatic invocation; cross-host coverage is incomplete |
| Weekly report | Reconciled captured records, approvals, failures and missing-data counts | A scheduled prompt does not prove execution, application of lessons, complete billing or future adoption |

`plugin_adapter.py` currently returns no routing output for `SessionStart`. `session_workflow_hook.py` applies `_prompt()` guidance only to recognized substantial work and skips nested agent events. `tool_scope_hook.py` gates supported edits and validates plan/QA schemas; `session_workflow_hook._validate()` compares reviewer labels and `retry_action()` uses submitted attempts. None of these authenticates agent dispatch. See [coverage.md](coverage.md) and [workflow.md](workflow.md).

## Negative acceptance cases

1. First-task execution without a routing decision: deny where the host can intercept execution.
2. Misclassified or ambiguous task: classification must not waive routing or required preparation.
3. Nested agent missing parent accounting, DoD or checks: cannot count as completed work.
4. Fabricated worker/model labels without observed dispatch: cannot satisfy delegation.
5. Fabricated reviewer or QA prose: cannot satisfy independently executed checks.
6. Fabricated attempt ladder: cannot affect observed failure counts or authorize escalation.
7. A quoted model name or model override: cannot establish human choice or bypass other gates.
8. Disabled/untrusted hooks, missing identity, unsupported tools or remote writes: report unavailable, not certified enforcement.

Run these against the installed native host, not only replay payloads. Test stale receipts, cross-session reuse, replayed completions, concurrent agents, changed artifacts and changed acceptance criteria as additional cases. Validate that normal conversation adds no unnecessary model calls or automatic continuations.

## Deployment boundary

A reliable implementation needs a host-controlled execution boundary that observes and authorizes every relevant operation. A receipt declared by the same model is not such a boundary. Extend only hosts that expose the necessary events; document remaining gaps rather than adding unverifiable fields. Ordinary GPT chat has no executable interception in this kit. A controlled replacement client would be a separate architecture decision, not equivalent coverage of the ordinary chat product.

No runtime, permission, trust setting, API integration or model selection is changed by this document. Current deployment evidence remains separate from this acceptance contract.
