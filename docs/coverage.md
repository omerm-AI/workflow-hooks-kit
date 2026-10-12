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
