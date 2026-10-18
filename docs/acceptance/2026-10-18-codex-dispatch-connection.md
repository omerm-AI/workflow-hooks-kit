# Codex native dispatch connection: bounded acceptance run

Status: **Open**. Three native attempts were used; no fourth attempt was made. No production routing change was deployed. Existing accepted hook source and configuration were restored after temporary probes.

## Model-free preparation

The installed native client reported version `0.162.0-alpha.17.2` and subscription login. No model API key was supplied. The supported app-server `hooks/list` response showed the delegation guard enabled and trusted, with no discovery errors. The same result held under the disposable process sandbox. This proves discovery and trust, not runtime interception.

Under operating-system outbound-network denial, a native first turn emitted completed SessionStart and UserPromptSubmit hook notifications. This confirms actual hook execution in the measured host, without a provider request. The test denied known user instruction/skill sources; it did not claim removal of vendor instructions or all host context.

Official upstream source suggested a flattened V2 tool identity could be rejected by the guard. A defensive normalization candidate passed local tests, but upstream main is not proof of the installed binary. Native acceptance was required before deployment.

## Actual native observations

| Attempt | Controlled change | Actual result | Acceptance |
|---|---|---|---|
| 1 | CLI dispatch with disposable-root-scoped identity normalization and metadata trace | Native thread API showed a real worker; no guard receipt or matching trace was observed | Failed; trace scope alone could have missed a callback |
| 2 | Direct app-server dispatch with session-scoped trace and full native hook notifications | Startup and prompt hooks ran. A real child started and completed, while no PreToolUse notification or guard callback was observed | Concrete unprepared-dispatch counterexample |
| 3 | Supported process-local model catalog selecting the legacy multi-agent version, with the V2 feature disabled | Offline rendering changed. In the actual turn, the parent reported spawn_agent unavailable, used no tool and created no observed child | Inconclusive for enforcement; tool absence is not a hook denial |

The second probe stopped capture on the child's completion, so it does not establish the parent's final completion. Its actual child-start event is sufficient to disprove the requested missing-plan gate for that measured path. Child default configuration is not evidence of the resolved worker model.

The legacy catalog was a temporary local snapshot. Only the selected parent/worker model metadata was checked for the intended single-field change against the subsequently observed cache; it must not be installed globally or treated as a stable catalog replacement.

## Rollback and publication

Each native probe restored the original installed guard bytes in a finally block. The native hook definition and trust data were not rewritten. The unproven normalization patch was preserved privately and removed from the public working source. No modified vendor binary, trust bypass or API-backed test was used.

Private native identifiers, paths, prompts, logs, settings, receipts and model catalogs are not included in this repository. This document is a sanitized result record, not a raw diagnostic attachment.

## Required next engineering gate

The active delegation execution path must expose an executable interception before child creation, or be replaced by a supported path that does. First demonstrate a native PreToolUse callback with actual dispatch identity. Then require a signed missing-plan denial and verify that no child was created. Only after those checks should a prepared-plan allow control, independent review and production rollout occur. Further model retries without a changed interception boundary are not justified.
