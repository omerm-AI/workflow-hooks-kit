# Local hook receipts

`claude-plugin/workflow-hooks-kit/scripts/hook_receipt.py` provides a small standard-library API for recording a bounded local observation and later correlating it with native event metadata:

```python
marker, receipt = hook_receipt.create(state_dir, native_payload, "success", hook_version)
verified = hook_receipt.verify(
    state_dir, marker, expected_session_id, expected_turn_id,
    expected_event, hook_version, "success",
)
```

The compact marker contains a 64-bit batch locator and a 128-bit random nonce. Every batch holds at most 100 receipts. At capacity, creation seals that batch with a checksum manifest, creates the next batch, and atomically advances the active pointer. Batches and consumed receipts are retained; nothing is silently deleted. If a process stops during rotation, the old receipt bytes remain intact and the next create safely validates the manifest before completing the pointer update. The marker selects one batch directly, so verification does not scan old batches.

Each receipt contains only its schema, UTC timestamp, event enum, hashed session identifier, turn hash (or `null`), nonce, batch number, outcome, hook-version hash, and HMAC-SHA256 signature. Claude `prompt_id` and Codex `turn_id` are accepted as the turn identifier; if both are present and disagree, creation fails. `SessionStart` may omit the native turn identifier and records a `null` turn hash. Every other event requires a real native turn identifier; none is synthesized. Input strings are bounded to 256 characters, receipt files to 2 KiB, and each batch to 100 receipt files. The default maximum receipt age is 24 hours; callers may choose at most 7 days. Receipts more than five minutes in the future are rejected. Verification consumes the receipt by atomically renaming `.json` to `.used`, so replay fails; the file bytes remain unchanged and match the batch manifest.

The state directory must already exist and be owner-only. Its HMAC key remains in that directory and is never returned. Losing the key makes retained signatures unverifiable. Batch manifests contain per-nonce SHA-256 checksums for exact recovery and are checked when a sealed batch is verified.

The local HMAC establishes integrity against accidental edits and unprivileged file substitution. It does **not** prove that a native host emitted the event: another process running as the same user can read or replace local state and can forge a local receipt. A real acceptance check must independently correlate the native event with the returned marker/receipt and run isolated enabled and disabled controls using benign prompts with no matching work instructions. Local replay tests alone are not evidence of native hook activation, event authenticity, or enforcement.

Callers must treat receipt creation or verification failure as a recording failure. An enforcement gate must fail closed when recording is required; it must not convert a missing receipt into a passing gate. The hook's own observer/runtime failure policy remains the caller's separate decision. Receipts contain no prompt text, tool inputs, raw identifiers, cwd, paths, or arbitrary payload fields.

## Native verification status

The response-language controlled sample matched real Code Local session and prompt metadata to signed SessionStart and UserPromptSubmit receipts; consumed markers could not be reused. A separate native unprepared Agent attempt was denied before dispatch and emitted independently verified failure receipts. These observations establish the tested event-to-receipt correlation only. They do not establish model/worker completion, semantic compliance for every prompt, Codex activation, or Cowork acceptance. Never manufacture receipts by replaying real native identifiers and then report them as native observations.
