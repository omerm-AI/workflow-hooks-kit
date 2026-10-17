# Strict enforcement: contract and current gaps

**Not implemented as a universal guarantee.** The local kit now implements a prerequisite gate for native `Agent` and `spawn_agent` calls: a protected native task identity and frozen READY substantial plan are required. This gate does not prove actual worker dispatch, model identity, completion, or independent review, and local tests do not prove native hook activation.

Deployment proceeds in this order: (1) Codex and Claude Code gates plus native acceptance, (2) ordinary GPT capability assessment and implementation where supported, then (3) Cowork. Evidence from the first phase does not certify later phases.

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

## Hook-origin acceptance

Native acceptance must isolate executable hooks from matching model instructions. In a disposable test scope, remove the tested work instruction from the prompt, project instructions, skills and memory where the host permits isolation. Preserve unrelated safety and permission controls. Use the same neutral test request with the hook disabled and enabled, in fresh equivalent sessions, and retain the different observed outcomes. Do not weaken the production installation for this control.

Each tested hook invocation must produce a unique local receipt bound to the native session/turn, event, hook version and observed result. A short matching marker in hook output is diagnostic, not sufficient proof. Validate it against the independently inspected local receipt and actual host event; reject missing, replayed, stale or mismatched receipts. Do not supply the expected marker in the test prompt or accept a model-authored receipt as provenance. Local replay alone cannot establish a native event, and a local signature cannot authenticate host origin against another process running with the same permissions.

If the host cannot exclude a relevant instruction source, report the causal test as unverified. Language instruction loading and actual Hebrew output are separate acceptance checks. The receipt helper and selected native controlled samples are implemented; universal per-handler receipt coverage and whole-system causal acceptance remain incomplete. The prerequisite gate alone does not deliver either guarantee.

## Deployment boundary

A reliable implementation needs a host-controlled execution boundary that observes and authorizes every relevant operation. A receipt declared by the same model is not such a boundary. Extend only hosts that expose the necessary events; document remaining gaps rather than adding unverifiable fields. Ordinary GPT chat has no executable interception in this kit. A controlled replacement client would be a separate architecture decision, not equivalent coverage of the ordinary chat product.

No runtime, permission, trust setting, API integration or model selection is changed by this document. Current deployment evidence remains separate from this acceptance contract.

## Bounded strict-dispatch investigation

The strict packet adapter was not accepted or rolled out. Its isolated local suite passed 160 tests, but a real Code Local Agent request was rejected by its assumed input shape and no child started. A separate independent negative probe found that a model-mismatched request was denied without a signed failure receipt. The investigation reached its ten-candidate failure limit; no further repair or global replacement was performed. The unaccepted source and sanitized findings are preserved on [the archive branch](https://github.com/omerm-AI/workflow-hooks-kit/tree/archive/strict-stage-candidate-10). The test project was restored exactly, and its test ledger was honestly closed as blocked with no QA PASS.

The accepted prerequisite-only companion remains separate from this failed strict candidate. Earlier native observations prove its tested deny/permit paths and an actual prepared worker, not mandatory routing or model-to-stage enforcement. The canonical request validator remains unwired on this branch. Loading the language hook is also distinct from compliance: a later native Agent run answered in English despite verified language-hook receipts. Neither local test counts nor signed load receipts certify universal enforcement.

## Native runtime-failure boundary

Claude Code 2.1.295 and later support `"onFailure": "block"` on a command handler. For a supported synchronous `PreToolUse` handler, this prevents a missing or crashed hook command from silently allowing the tool. See the [official failure-policy reference](https://code.claude.com/docs/en/hooks#block-the-action-when-a-hook-fails). Do not assume that another host or an older embedded Code runtime supports this field. Stop-family and background hooks have different semantics.

A native Code Local controlled test used an absent executable with an unpredictable filename and the identical neutral request to run `pwd`. Matching work instructions and automatic memory were excluded in the disposable fixture. Without the field, the actual Bash tool returned its working directory. Adding only `onFailure: block` produced a native failed-tool card naming the exact missing executable and saying the engine blocked because of that field. Independent metadata-only callbacks correlated each native prompt. The callback was then removed and the fixture settings restored exactly.

This proves the tested host's failure-policy boundary. The absent script never ran, so it could not sign a receipt. A native engine error is distinct from proof of script execution; never manufacture a receipt for this case. The original installed file-scope/ledger handler subsequently received this field without changing its command, source bytes, unrelated settings or delegation companion. A real native invalid-ledger command was then rejected by that original handler. Runtime fault injection was confined to the disposable project; no global fault injection or universal crash coverage is claimed. The field cannot catch a script that swallows its own exception and returns valid warning JSON with exit zero. The narrower source improvement below addresses known internal pre-tool exceptions; malformed CLI input remains a separate gap.

The generic installer does not currently add this version-dependent field. On a verified compatible host, modify the existing owned handler in place rather than registering a duplicate. Account for exact-definition installer ownership before changing an installer-managed object: a manual edit can otherwise stop a later upgrade or uninstall from recognizing it. Native acceptance is still required after any deployment.

## Known file-gate internal exceptions

The current source now returns a bounded `permissionDecision: deny` when an internal exception escapes a recognized `PreToolUse` edit or Bash handler. It exposes only the exception type. Existing special ledger-command and delegation error branches remain unchanged. Four focused tests cover ledger creation and lock failures in both runtime modes, known edit/Bash errors, existing specialized denials, and normal read-only/conversation paths; the independent full kit suite passed 141 tests.

A separate native fault-injection control used the same neutral `pwd` request in fresh equivalent sessions, with matching static policy and memory excluded. An isolated wrapper injected the same `OSError` into each frozen core version and signed the actual native callback result. The original core returned valid warning JSON and the actual Bash tool executed; the changed core returned deny and the native tool card displayed the matching receipt marker without executing Bash. Independent prompt metadata matched both signed receipts, which were verified and consumed. A first harness error was preserved as an invalid baseline, fixed, and checked synthetically before these two valid samples. Temporary handlers were removed and fixture settings restored exactly.

This is controlled native evidence for the exception fallback, not a global production rollout or production per-handler provenance. Malformed/oversized CLI input, missing event/tool identity, and unrelated tools retain separate unresolved behavior. It does not turn the Bash path into a general shell-write authorization system. A live rollout must also preserve account-plugin source-byte deduplication and native trust; do not overwrite a differently configured live core blindly.

The same two-line fallback was subsequently ported to the existing private legacy core without importing unrelated delegation behavior. Exact rollback copies and source/configuration fingerprints were retained. Global Codex and Claude core files and the owned synced account package were updated together, leaving existing hook command definitions unchanged. Actual old and fresh Code sessions both rejected an unsupported ledger command through the original global handler. The fresh session's actual plugin callbacks recorded global deduplication, with loaded package/source bytes checked independently. The current Codex session also observed the original handler reject that command after the update. These checks prove the stated normal gate and dedup paths; global exception injection, a fresh Codex session and universal interception are not certified by them.

## Configuration writers and runtime versions

The installed standalone CLI and Desktop's embedded Code runtime can differ. In a native maintenance test, CLI 2.1.293 serialized shared settings during a local plugin install/uninstall and removed the newer `onFailure` field. The exact prior configuration was restored after verifying that unrelated settings were unchanged. An official CLI self-update to 2.1.302 completed without changing that restored configuration. Both observed standalone installation paths then reported the new version. A real local fixture install/uninstall under an isolated [`CLAUDE_CONFIG_DIR`](https://code.claude.com/docs/en/env-vars) preserved `onFailure: block` and the fixture environment setting after each operation; the real settings stayed byte-identical. No model was started by that metadata-only test. Re-read owned settings after any installer or configuration writer; an enabled indicator or a successful plugin command is insufficient evidence that newer fields survived.

Desktop Code-mode uploads and Claude account uploads can also target different plugin stores. The first attempted upgrade created a local owner alongside the existing synced account owner. That new owner was disabled/uninstalled with its data preserved before the account package was replaced through the account UI. Do not keep both merely because they share a display name. Verify plugin identity, scope, actual loaded source and runtime deduplication separately.

## Core and adapter execution receipts

The command entry points of `tool_scope_hook.py` and `plugin_adapter.py` now create local HMAC receipts using `native_receipt.py`. Direct Python `run()` calls remain unsigned testable functions. The version binds the handler identity and exact bytes of its core, workflow and receipt dependencies. Each receipt uses the supplied native event and session/turn identities; missing or conflicting identities cannot be replaced with generated identifiers. Receipts contain hashes and bounded outcome metadata, never tool inputs, prompt content or transcripts. They add no model context or model invocation. Global/plugin deduplication now requires all four runtime source dependencies to match, including both receipt helpers; a deduplicated adapter records `skipped`.

For a recognized edit/Bash `PreToolUse`, a missing helper or unsafe/unwritable receipt state causes denial while preserving an existing denial reason. Conversation and Stop receipt failures emit a bounded stderr diagnostic without an additional continuation. Existing malformed/oversized-input behavior remains separate. Core bookkeeping can occur before receipt creation; the pair is not an atomic transaction. A `success` receipt means that the handler returned without a classified denial/warning, not that the task or its QA passed. The receipt does not itself bind a tool-use identifier, validate a QA claim, authenticate the native host against another same-user process, or prove that a model followed an injected instruction.

The independent full local suite passed 166 tests, including actual entry-point subprocesses, signed allow/deny, four-dependency deduplication, missing-helper refusal, unsafe state/key paths, identity conflicts, changed source and one-time verification. These subprocesses use synthetic identities and isolated state and are not native-host acceptance. Native deployment and causal coverage must be recorded separately. An absent/crashed executable can only have a native engine failure witness, not a script-produced receipt.
