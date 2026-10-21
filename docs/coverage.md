# Ten workflow mechanisms and their public coverage

| Mechanism | Public implementation | Limit |
| --- | --- | --- |
| 1. Cheaper-model advisory | Base policy asks for the cheapest adequate available model and a declared rationale. | Policy only: no automatic model picker, paid API call or model switch. |
| 2. Preparation | Material prompt classification and compact/substantial plan validation. | A narrow classifier can miss intent; explicitly declare substantial work when needed. |
| 3. File mutation gate | Recognized Edit/Write/apply_patch boundaries require a plan and scoped paths. | Shell parsing is partial; generic MCP writes are unchecked. |
| 4. Touched-path observer | PostToolUse records recognized local paths and uncertainty metadata. | It cannot prove every shell effect or connector write. |
| 5. Completion gate | QA fields, optional declared local file assertions and a one-time Stop block. | Free-text evidence and reviewer labels are declarations; subsequent Stop is not a pass. |
| 6. Reversible project hygiene | Policy requires reviewed same-project Old/YYYY-MM archival; touched paths aid review. | No automatic cleanup, deletion, or archive move; agent judgement remains required. |
| 7. Delegation and retry discipline | Substantial plans declare workers/boundaries/dependencies; QA labels must differ. A local helper validates a supplied retry ladder and recorded attempts. | No agent scheduling or model escalation is executed; absent attempt records cannot be counted. |
| 8. Preference learning | Optional local learning CLI produces explicitly approved scoped standards; agent reads a relevant one on demand. | No automatic transcript scan, profile injection, or cloud synchronization. |
| 9. Failure learning | Optional local learning CLI records authorized failure material and proposed lessons. | A lesson requires explicit local approval; it does not automatically alter runtime policy. |
| 10. Recall integration | Documented optional separate Total Recall installation. | Not bundled, invoked or configured by this kit; never claim recall is active without host evidence. |

The kit covers its exact event/tool contract, not every interpreter, connector or host release. Policies express expected agent behavior; only the explicitly described hook checks can deny a recognized operation. Read [workflow examples](workflow.md) before using the sentinels.

## Observed host status — 2026-10-18

This is a qualified acceptance snapshot of a compatible local deployment and its optional adapters, not a promise that the public installer enables every integration. “Observed” applies only to the named supported paths and scenarios. A signed callback, a policy instruction and complete enforcement are different outcomes.

| Mechanism | Codex | Claude Code Local | Ordinary ChatGPT | Hosted Cowork |
|---|---|---|---|---|
| Cheaper-model selection | Heuristic advisory; no authenticated automatic routing | Policy only | Policy only | Policy only |
| Plan before supported edits | Native bookkeeping gates observed; universal routing incomplete | Native unprepared Write denied; isolated ON/OFF Write causality proven | No kit interception | Not proven |
| Intended project/file scope | Supported-tool validation; shell/MCP gaps | Supported-tool validation; shell/MCP gaps | No kit interception | Not proven |
| Touched paths | Partial native event coverage | Partial native event coverage | No kit interception | Not proven |
| Completion and QA | Structural gates/literal assertions; semantic limits | Structural gates/literal assertions; semantic limits | Policy only | Not proven |
| Project hygiene | Reminders and reviewed manual archival | Reminders and reviewed manual archival | Policy only | Policy only |
| Delegation and escalation | Latest native collaboration probe completed without a guard receipt; enforcement failed for that observed path | Prerequisite observed; strict model/stage binding not accepted | No kit interception | Not proven |
| Preference learning | Local pending intake/review verified; new approved-rule future use incomplete | Automatic checkpoint and scoped reads observed; full lifecycle incomplete | Cloud synchronization unverified | Manual scoped read observed; automatic capture unverified |
| Model-failure learning | Local records/review; calibrated automatic routing incomplete | Complete observed outcome chain unverified | Not proven | Not proven |
| Recall | Separate queried integration | Separate integration; not bundled by this kit | Not bundled | Not bundled |
| Shared checkpoint | Native old/new samples previously correlated | Native old/new samples previously correlated | Not proven | Automatic path unverified |
| Weekly review/report | Updated native automation ran the atomic review and maintenance, returned a short report; timer origin of this invocation not independently proven | Shared local queue, not a separate Code scheduler | No verified synchronization | Only captured shared records can participate |
| Hebrew response | Written user preference, not a language interceptor | Hook loading and neutral samples observed; an earlier English counterexample prevents an always-Hebrew claim | Written preference only | Hook effect unverified |
| Execution provenance | Direct prompt, Stop and supported tool samples verified | Core/adapter/language/prerequisite samples verified | No kit callback | Automatic callback coverage unverified |

After user-reported native trust approval, one deliberately unprepared Codex collaboration probe still completed with zero prerequisite-guard receipts before and after. The cause is unresolved; do not relabel it as failed trust, or claim that every Codex agent path bypasses hooks. It is not a reset of the strict-delegation candidate limit.

An earlier Claude Desktop isolation test backed up work-instruction sources, disabled automatic memory and requested exclusion of instruction files only in a disposable project. Its native context inventory showed no memory-file category, but MCP server instructions and other messages remained. Actual Write attempts were denied by the original hook before creating the output, with correlated signed receipts. Fixture settings were restored exactly and global configuration remained unchanged. That earlier sample alone does not prove completely empty user context. Keep vendor safety controls intact; never remove global production instructions just to obtain a passing isolation label.

An initial authorized standalone subscription test observed a native Write denial but retained an unresolved built-in instruction-source question. A subsequent [controlled ON/OFF experiment](acceptance/2026-10-18-claude-write-causality.md) closed user-work-instruction isolation for that supported Write case: final instruction-file inventories were empty in both arms; only the original workflow hooks differed; Write was denied when enabled and created the exact output when absent. Actual native prompt/session witnesses and source-bound HMAC signatures were independently checked. Vendor system instructions remained, and full system-prompt bytes were not compared. The result does not validate other mechanisms or every write path. Subscription authentication and the actual Haiku 5.5 model were verified; no direct API key was configured. Do not use bare mode as an isolation substitute because it skips hooks. See [Claude memory exclusions](https://code.claude.com/docs/en/memory) and [native environment controls](https://code.claude.com/docs/en/env-vars) for configuration choices.

The [binary status register](hook-status.md) is the current per-mechanism, per-host acceptance view. A configured handler or passing replay alone never changes an unresolved outcome to Tested and proven.

The next substantive work is authenticated routing, wider write-path coverage, genuinely isolated host acceptance, approved-learning application/future-use evidence, and separately verified GPT/Cowork interception. Native callback counts must not be converted into a completion percentage.
