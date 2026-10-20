# Bounded safe-check acceptance

Date: 2026-10-20. Preview: `hygiene-safe-check-preview-2026-10-20`.

## Contract prepared before implementation

Run local checks without authorizing ordinary shell execution or changes to project files. Require actual operating-system confinement, positive scratch/read success, explicit failures for project/outside writes, private outside reads, child creation and network access. Bound time and output. Unsupported requests never execute. A process exit zero must not approve independent QA or pending hygiene review.

## Measured results

| Check | Status | Evidence |
| --- | --- | --- |
| Real macOS kernel acceptance | Tested and proven | Fourteen independent tests: project read/scratch write, overwrite/create/delete/rename denial, outside write/read denial, symlink denial, fork/spawn/subprocess denial, network denial, timeout, output cap, nonzero exit and malformed input refusal. |
| Actual installed Codex and Claude commands | Tested and proven | Fresh installed homes; recorded commands executed under a different caller HOME. Valid check passed, overwrite failed, source bytes unchanged and workflow QA Stop remained blocked. No model calls. |
| Full regression suite | Tested and proven | 238 unittest cases passed. Receipt fixtures bind the added source and plugin dedup requires the new helper. |
| Independent security review | Tested and proven | Separate reviewer inspected final sources and exercised scratch symlink to project, parent signal denial and bounded cleanup retention. No blocking finding for the single-process scope. |
| Updated Codex trust | Tested and proven | Native discovery reported the two scope definitions trusted. No thread/turn start or inference. |
| Actual native Codex safe check and edit denial | Tested and proven | Actual installed scope command, isolated workflow HOME with normal subscription auth/config: exact safe-check output, then actual apply_patch denied for missing hygiene preflight; target absent. Two signed native/source-bound receipts independently reverified. Eight source components unchanged; global markers absent. The test-only UPS prepared a true baseline plan without hygiene review; full empty-context isolation is not claimed. |
| Actual native Claude safe-check success | Open | One subscription request reached the unchanged fresh installer command with matching three signed callbacks, empty observed instruction/MCP/skill inventories and vendor sections preserved. The check refused execution because the outer test harness sandbox prevented inner Seatbelt setup. No native success claim. |
| Inherited sandbox refusal | Tested and proven | Model-free diagnosis compared identical installed commands: direct execution passed; inherited Seatbelt returned sandbox_apply Operation not permitted, even with an allow-default outer profile. Added actual-kernel regression proves unsupported status and no untrusted check execution. |
| Global strict adoption | Open | Policy remains disabled by explicit operator decision. Existing edit/Old/next-edit evidence does not prove all sessions adopted this preview. |

The first implementation failed its backend canary because creating a socket was permitted while connecting was denied. It refused all checks rather than reporting success. The canary was corrected to verify connection denial with EPERM/EACCES; independent positive and negative acceptance then passed. Receipt regression fixtures were updated for the new source component; no required check was removed or weakened.

## Exact scope and limits

- macOS Seatbelt through the installed `/usr/bin/sandbox-exec`; a private/deprecated platform interface requiring runtime preflight, not a universal portability claim.
- Single process only. Fork, posix_spawn and subprocess are denied. Exec may replace that process; the same sandbox remains effective.
- Read access: project, private scratch and selected system interpreter/runtime roots. Metadata is readable globally; this is not general confidentiality or same-account tamper resistance.
- Writes only to unique private scratch. No project cleanup is performed by checks. The original intercepted shell request is denied and receives structured process evidence.
- Shared timeout 1–3 seconds including backend verification; output at most 8192 bytes. Cleanup at most 128 entries and depth eight, with excess private scratch reported retained. No total disk/memory quota.
- No accepted Linux/Windows backend, long-running checks, child-process builds or project-output generators. Refusal is not a successful test; do not bypass it.

Only generic source and summarized acceptance are public. Local paths, account metadata, native identities, credentials, transcripts and raw observer evidence remain private.

## Native trial boundary

The Claude native trial reached the agreed attempt cap. No additional subscription call was made after the failed acceptance. The operator must review an additional attempt before it runs. The prepared next harness removes only the outer test sandbox; the installed inner runner, vendor context protection, empty observed work-context checks and one-request cap remain. No product security restriction is removed to obtain success.

The fresh public Codex profile login/trust prerequisite in the first-install record remains a distinct Open item. The successful native Codex trial used the normal existing subscription configuration and actual installed private-compatible command with isolated workflow state; it is not substituted for a new customer's login.
