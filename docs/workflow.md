# Workflow contract

The host supplies a native session ID, turn ID (or Claude prompt ID), event name and project `cwd`. The project must be an existing specific directory, outside `/tmp` and broad home/system roots. These hooks do not manufacture a missing native identity. Your first Write without a plan is denied with preparation guidance.

In a native Bash tool call:

```sh
workflow-ledger plan '{"definition_of_done":"Create the requested text file","outputs":["notes.txt"],"qa":{"check":"Read notes.txt","expected":"Contains the requested text"}}'
```

The hook saves this plan and denies execution of the sentinel. Retry the intended Write/Edit. Run the actual check. Then:

```sh
workflow-ledger qa '{"state":"complete","qa":{"evidence":"Read notes.txt and confirmed the requested text","verdict":"pass","reviewer_id":"lead"}}'
```

A prepared plan may include `qa.assertions`, for example `"assertions":[{"path":"notes.txt","expected_text":"checked"}]` inside `qa`. This compares exact UTF-8 file contents, not a substring. Each path must match a declared relative output. Assertions are frozen with the plan; files and expected text are limited to 16KB each. Keep evidence specific. `state: blocked` needs a `blocker`; `state: awaiting-user` needs a `question`.

For substantial work, a classified prompt creates a preparation record, or explicitly start with `workflow-ledger start substantial`. Then submit a plan like:

```sh
workflow-ledger plan '{"stages":[{"number":1,"name":"Implementation","definition_of_done":"Requested output works","worker_id":"worker-1","worker_model":"available-model","worker_effort":"medium","model_rationale":"Adequate for the scoped implementation","inputs":[],"boundaries":["Current project only"],"dependencies":[],"outputs":["result.txt"],"qa":{"check":"Inspect output","expected":"Requested result"}}]}'
workflow-ledger qa '{"state":"complete","stages":[{"number":1,"qa":{"evidence":"Inspected result.txt against requirements","verdict":"pass","reviewer_id":"reviewer-1"}}]}'
```

Replace model/reviewer labels with actual available identities. No model API is called. A passing label does not create evidence. `workflow-ledger continue` can explicitly carry a compatible incomplete same-project plan to the current native turn; carried QA becomes pending.

The sentinel plan API does not accept allowed-roots changes. The runtime recognizes an `allowed_roots` field in a manually maintained local ledger, but expanding scope requires explicit user authorization and careful local review; it is never inferred from a request. A plan can be accepted while a subsequent outside-project Write remains denied. Stop blocks once for incomplete material work, asks for honest completion/blocker evidence, and does not create infinite paid continuations.
