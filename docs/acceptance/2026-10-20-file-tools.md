# Limited native-file-tools acceptance

Date: 2026-10-20. Preview: `hygiene-file-tools-preview-2026-10-20`.

## Approved contract

The operator explicitly selected known native file-save gates, with uncovered write paths disclosed. `--hygiene-file-tools` gates recognized native Edit/Write/apply_patch-family calls and pending-review Stop. Ordinary shell commands, connector/MCP calls and unrecognized wrappers retain baseline behavior. They are **Open** for hygiene interception. This mode must not be presented as strict all-write coverage.

The separate `--hygiene-enforcement` mode keeps its existing strict unknown-tool and shell refusal. Selecting both flags or silently replacing an existing conflicting policy is refused before mutation. No account key, transcript or private receipt is part of this release.

## Model-free measured evidence

| Check | Status | Evidence |
| --- | --- | --- |
| Full regression suite | Tested and proven | 247 unittest cases passed after the dangling-policy repair. The strengthened focused suite passed eight cases, including both-host Read and Stop failures for a dangling policy symlink. |
| Limited mode boundaries | Tested and proven | Actual adapter calls preserve ordinary shell/unknown-tool baseline, while strict mode still denies those identities. Known edits require plan, file review, exact previous-byte backup and post-edit review before another edit or completion. |
| Installation/coexistence | Tested and proven | Both installer variants write the exact selected mode, preserve foreign settings, remain idempotent and refuse conflicting modes. |
| Fresh/populated project installed-command replay | Tested and proven | Both hosts, four new/existing-folder cases: actual recorded hook command, separate caller HOME, edit backup, pending-next-edit denial and Stop block/release. No model calls; not native session inference. |
| Actual reviewed cleanup and recovery | Tested and proven | Both installed commands archived an eligible byte-identical PNG duplicate, transferred an eligible helper to Assets and restored a file without overwriting. Original hash and mtime were verified. Referenced media and source-file archiving were refused. |
| Codex native adoption and persistent activation | Tested and proven | Twenty independent checks passed: same live process/thread before/after activation, actual cleanup/edit/Old bytes, next-edit and Stop refusals, and fresh-thread refusal. Eight source hashes and one Pre/Post handler were rechecked; watchdog exit was verified before persistent limited-mode activation. |
| Claude native adoption and persistent activation | Tested and proven | Corrected second trial passed all 23 independent checks in the same live process/session and a fresh session. Five SDK model steps were forwarded, bounded 1+3+1. Current eight-source hashes, settings and single owned event handlers matched. Watchdog exit was verified before permanent limited-mode activation. |

The prior code treated a dangling policy symlink as an absent policy. It now refuses validation instead. The negative regression uses a Read that baseline would allow and checks the hygiene-specific failure reason, plus Stop. Missing-plan rejection alone is not accepted as proof of the repair.

## Scope of cleanup

Installation changes host settings and runtime only. It does not scan or move historical project files. Existing project folders have no age exemption for later supported operations. Existing sessions are a separate acceptance boundary: they must have registered callbacks and demonstrated adoption, or be reloaded and tested.

The implemented transfer engine accepts reviewed eligible media/PDF assets, with bounded literal local reference checks. It does not prove arbitrary semantic, dynamic or external dependencies and does not automatically classify arbitrary text/source/office drafts. Uncertain files stay in place. No permanent deletion is performed. Backup copies and transfer manifests live under the selected project root's dated Old archive; required project structure stays intact.

The public [customer guide](../customer-install.md), [customer status](../hygiene-customer-status.md) and two platform-specific prompts describe fresh-profile login/trust, exact commands, native canary acceptance and recovery. A disposable existing folder is not evidence that an already-running session loaded newly installed hook definitions.

## Codex native lifecycle boundary

The process and old thread were genuinely alive with registered callbacks before mode activation. The baseline created a real file while policy was absent. After activation, that same process/thread submitted an actual review sentinel, edited the file and attempted a second edit; the hook archived the original bytes and mtime, denied the next edit and blocked Stop. An eligible PNG duplicate was archived and an eligible helper moved to Assets. A different thread created after activation attempted a native edit and was denied while the first owner's review remained pending. Local HMAC verification bound receipts to the native identities and current eight-source version.

A disclosed exact-workspace UPS fixture supplied only the true compact baseline plan; it did not grant hygiene review. The temporary fixture source was restored exactly. Three native turn starts were bounded by deadlines and interruption at the required Stop block. Exact provider-request counts are unavailable in this installed Codex transport and are reported unknown, never zero or a measured cap. Normal subscription auth was used without API-key fallback.

This proves mode-marker adoption by a process with callback definitions already registered. It does not demonstrate that installing new definitions hot-reloads them into every previously opened process. Such sessions must reload or supply their own native callback proof. Persistent activation preserved host settings and the existing private-compatible runtime; it did not overwrite it with the generic installer or add duplicate handlers.

## Claude corrected native lifecycle

The first trial is retained as a failed test-control attempt: native hygiene gates worked, but the SDK rejected its observer because a helper receiving `$` was not declared at module top level. Request forwarding therefore was not measured, and the fresh session made a further denied Bash call. That trial is not used as passing cost-control evidence.

Before trial two, the exact observer module was validated under network denial and used for two zero-inference inputs in the same process/session. The corrected module uses inline SDK calls and an operator-only test flag: default zero forwards no model; only the root-authorized native controller enables forwarding. Prompt counters and both hook invocations were observed before the paid trial. The earlier fixture, evidence and pending owner state were preserved in their original separate root.

The second trial passed all 23 checks and independent lead/reviewer verification: baseline native Write before activation; same PID/native session after activation; real review sentinel; duplicate archival and helper transfer with verified hashes/mtime; native overwrite with exact Old beforeimage; next Write denied; actual Stop blocked; and new-session Write denied while pending review remained. Five SDK model steps were forwarded (one baseline, three postactivation, one fresh). This measures SDK forwarding, not hidden provider retries or a total monetary price. The test observer is not installed as a recurring product hook.

Filtered explicit settings overlays retained the real global callback commands unchanged while excluding credential/provider environment fields and apiKeyHelper. The observer retained vendor context. This proves that those callbacks use actual global private-compatible state; automatic default settings discovery and every hidden/static context remain distinct boundaries unless separately witnessed. No API-key or paid API fallback was used.

Both experimental watchdog processes exited successfully and their markers were recoverably archived before permanent file-tools markers were created. Actual source hashes and unchanged settings were checked again immediately before each activation. Codex has one owned scope handler in each Pre/Post event; Claude has one in each UPS/Pre/Post/Stop event. Permanent activation added no hook definition or duplicate callback.
