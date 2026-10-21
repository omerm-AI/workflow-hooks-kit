# Cowork automatic checkpoint: diagnostic decision plan

Status: planned. This document is not runtime acceptance or a deployment claim.

## Investigation checkpoint — 2026-10-17

The read-only boundary investigation and one final route candidate were run in
native Cowork. Command hooks fired in a fresh session with the exact installed
package bytes. A model-invoked host connector read also succeeded. Routing the
MCP hook through the observed `remote-devices` server/tool naming still produced
no matching host receipt, both cold and after a successful read warmed the
connection. Active and archived host receipts were checked. The default cloud
receipt file was absent. The prior account package was restored; no new route
is advertised as working and no universal rollout is claimed.

Two diagnostic pitfalls were caught: native Bash and device command tools can
run in different filesystems, and the kit's health record retains only the
first event of each type. A saved fixture or old health mtime is not liveness
evidence. An existing cloud session can retain older plugin files while account
metadata displays the newer version; inspect actual loaded bytes separately.

The effective MCP inventory available to the hook dispatcher and its exact
failure reason remain unknown. This result does not prove a vendor defect.
The repair-iteration review gate now applies; do not add more wiring variants
without operator review. A version-pinned retest after an official client
update is an option, not an established remedy. The remaining plan below stays
open, including policy consumption and the complete learning lifecycle.

## Outcome and known evidence

An actual human submission in an existing and a new supported Cowork session
must automatically reach the intended shared learning store before the model,
using actual native identities. Applicable approved policy must also be consumed;
a receipt or fingerprint alone does not prove that. Existing Code and Codex
behavior must remain intact. Inferred rules require operator approval.

Observed: Cowork command hooks fired; model-invoked local connector reads worked;
native-identity and static-input MCP hook probes produced no matching host
receipt. Therefore investigate the dispatch boundary before more payload changes.
Enabled indicators, schema checks and unit tests are not native acceptance.

## 1. Map the actual boundary before changing configuration

Record the installed product/runtime versions, actual execution mode, plugin
load status, effective registration, configured MCP server inventory and exact
successful manual-read route in one dedicated native session. Do not infer
execution mode or native identity from an app window or chat URL.

Map each observed arrow:

`user event -> hook runner -> MCP client -> server/bridge -> broker -> store`

Use `claude plugin list` only as non-model inspection where available. Read only
kit configuration and bounded diagnostic metadata. No raw transcripts, environment
dumps, unrelated projects, Desktop internals or trust bypasses. Do not start
models through CLI/API. A model-visible bridge tool is not assumed addressable
by the hook runner's own MCP client.

## 2. Discriminate hypotheses

| ID | Hypothesis | Minimum test | Decision |
| --- | --- | --- | --- |
| H1 | Hook runner and local tool use different execution contexts | Compare runner host/mode, client server inventory and successful read route | If the server is bridge-only, require an observed bridge route before changing names |
| H2 | Effective server identity differs from configured identity | Compare actual client registration with hook server; distinguish server name from model-facing tool name | Correct only an evidenced mismatch; do not guess colon/underscore aliases |
| H3 | First submission precedes connection readiness | Compare cold first submission with warm second submission after one read-only connector call | Only-warm success supports a readiness race; increase timeout only with timing evidence |
| H4 | This runner cannot dispatch MCP hook handlers | Compare command control and read-only MCP handler when warm; inspect a known-missing-server control's native diagnostic | No MCP dispatch despite a working command control points to handler/client boundary, not input templates |
| H5 | Bundle is stale, invalid or shadowed | Compare loaded version/hash and plugin list with staged package/effective registration | Repair only kit-owned load/registration failures; preserve unrelated hooks |
| H6 | Broker receives but rejects data | Compare bounded invocation-entry metadata before validation with receipt after validation | No entry means dispatch/transport; entry without receipt means identity/schema/exemption |
| H7 | Wrong store or lookup hides receipts | Match actual native identity hashes, intended store and timestamps; inspect known archives only if needed | Repair routing/lookup; never create synthetic native success receipts |
| H8 | Timeout or result parsing discards the outcome | Compare broker entry/receipt timing and native handler completion/output | Separate transport success from delivered policy and actual consumption |
| H9 | Duplicate installation or recursion creates inconsistent behavior | Count effective owned handlers and follow one native event; inspect native agent/schedule provenance | One effective owner; idempotent capture; report unsupported provenance explicitly |

One session should answer several read-only questions. Do not create nine
sessions. Fresh sessions are reserved for cold-start acceptance or proven reload
requirements. No blind retries or repeated sleeps.

## 3. Choose a repair or prove the capability boundary

1. Prefer a supported route correction, bounded readiness handling or actual
   registration fix. Change one variable per repair, retain before-image and
   failed evidence, then run the predeclared discriminating test.
2. If native MCP dispatch is unavailable, test whether a connected folder is
   truly projected into the hook runner with bidirectional visibility. A
   tool-mediated file service is not a shared filesystem. Only if proven,
   evaluate a versioned policy snapshot plus metadata-only outbox. Reject it
   if it loses first-message freshness, cross-project coverage or deterministic
   consumption, or needs manual per-session setup.
3. A reachable authenticated remote service is a separate architecture option.
   First establish hook-client reachability. New exposure, credentials or
   materially broader access require explicit approval before deployment.
4. A reminder followed by a model tool call is only a disclosed interim workflow;
   it does not meet automatic before-model acceptance. Do not rename it a fix.

If there is no supported route and alternatives fail requirements, return the
proven boundary and concrete choices for operator review. Do not promise every
platform limit can be fixed inside a plugin or install a standing agent.

## 4. Native acceptance matrix

| Case | Required evidence |
| --- | --- |
| Fresh cold session, first human message | Exact native identity receipt, callback ordering, no manual checkpoint |
| Existing session, next human message | Current package/policy used with no manual bootstrap |
| Warm second message | Same guaranteed path without duplicate proposals/history loss |
| Ordinary conversation | Zero custom context, zero learning-triggered model calls or continuations |
| Substantive work | Approved scoped standards applied to DoD and deliverable QA; total custom context at most300characters |
| Nested agent and scheduled work | Actual native provenance, proper exclusion/parent accounting; unsupported markers never invented |
| Repeated event | Idempotent capture and one effective owner |
| Disconnect, timeout, malformed data | Bounded explicit failure; no false PASS, hang or paid retry loop |
| Approved policy change | Next native consumer sees the revision and applies it; fingerprint alone insufficient |
| Proposal and weekly handoff | One pending intake, inactive before exact operator approval, approved scoped change reaches consumers; actual scheduled execution and short report observed |

Use isolated synthetic fixtures for negative/destructive cases. Do not create a
production preference to obtain a green test. Actual canonical activation needs
operator approval of the exact rule.

## 5. Cost, iteration and publication controls

- Start with free metadata/protocol/source checks; native subscription UI probes
  only where necessary. No model API/CLI, transcript imports or standing reviewers.
- Measure latency, context, continuations, duplicate handlers and state growth.
  Bounded transport waits are not model retries; characters are not billing proof.
- At most three failed hypothesis-backed repair cycles before operator review.
  Reconcile prior attempts before another repair; this plan does not reset them.
- Independent final review requires actual artifacts and native evidence. Missing
  runtime proof cannot become PASS through reviewer agreement.
- Keep the released package unchanged until required acceptance passes. Publish
  only generic code, synthetic tests and accurate limitations. No operator paths,
  IDs, runtime logs, policy contents or business data. Remove temporary probes
  after their diagnostic purpose ends, preserving recoverable evidence privately.

## Sources and limits

- [Official hook naming and connection semantics](https://code.claude.com/docs/en/hooks#mcp-tool-hook-fields).
- [Official Cowork architecture](https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview).
- [Independent Desktop bridge analysis](https://github.com/yaniv-golan/cowork-harness/blob/main/docs/fidelity-gaps.md): an implementation lead, not an official support contract or proof of the installed runtime.
- [Startup race report](https://github.com/anthropics/claude-code/issues/57932): historical SessionStart case; does not prove UserPromptSubmit has the same failure.
- [Silent hook failure report](https://github.com/anthropics/claude-code/issues/82323): diagnostic lead, not proof of this failure.
- [Retracted registration report](https://github.com/anthropics/claude-code/issues/93264): author found malformed plugin JSON. Do not apply the broad settings-overwrite workaround.
