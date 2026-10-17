# Claude Code response language hook

This optional, local hook adds one fixed response-language instruction at `SessionStart` and, at most once, to `UserPromptSubmit` per native session and installed language-hook version. It supports Hebrew (`he`) and English (`en`). Directives are at most 43 characters; stamped directives are at most 98 characters including their receipt marker. They preserve code, filenames, commands, and Git terms. The actual substantial-workflow context (198 characters) plus either stamped directive stays within 300 characters (293 for Hebrew, 296 for English). This budget excludes unrelated third-party context. The hook does not inspect prompt meaning, call a model, save prompts, or prove that a response follows the requested language.

With the configured `--state-dir`, each `SessionStart` (including resume/compact starts) emits the language directive and refreshes a small cache keyed by a hash of the native session ID. The first prompt in an already-open session also emits once if no matching cache exists. Later prompts in that session and version return no language context and may create a signed `skipped` receipt locally without an inline marker. If that receipt cannot be written, the hook returns only a bounded diagnostic message; it does not add language context or invalidate the cache, and retries receipt creation on the next event. A changed language or installed hook version emits once again. Independent sessions use separate cache files. The cache records only hashes, language code, and hook-version hash in owner-only files; it never stores raw IDs or prompt text. Cache writes are local output observations, not acknowledgements from Claude that it consumed the directive before a timeout. If IDs/cache validation/locking fail, the hook fails open by emitting again rather than falsely suppressing. Without `--state-dir`, it emits on every supported event as before.

The language instruction has a separate context cost from workflow and project-hygiene instructions, but the cache avoids charging each ordinary prompt. It does not change the workflow kit's planning or hygiene behavior. Native event payloads are accepted on a best-effort basis; malformed, oversized, unsupported, and nested-agent events produce no context and do not fail the hook. The presence of a native event field does not authenticate its origin. A successful local replay does not prove Claude Code loaded the hook or that the model complied semantically.

## Install or change language

Run from a copy of the kit:

```sh
python3 tools/configure_language.py --language he
# Or:
python3 tools/configure_language.py --language en
```

`--home PATH` selects an alternate home for an isolated configuration. The tool configures Claude Code only at `PATH/.claude/settings.json`; it does not configure Claude Cowork or a plugin. It copies the hook and its receipt helper to `PATH/.claude/workflow-hooks-kit/bin/`, then adds owned `SessionStart` and `UserPromptSubmit` command hooks. The hooks enable signed local receipts under `PATH/.claude/workflow-hooks-kit/language-receipts/`. Existing permissions and unrelated hooks stay intact. Repeating the same install does not add duplicates. Running the command with the other language replaces only this tool’s unchanged owned handlers.

Before changing settings, the tool saves their exact previous bytes in `PATH/.claude/workflow-hooks-kit/backups/`. If `settings.json` was absent, it records that fact in a `.settings.absent` backup. These backups are recovery evidence. If a settings, runtime, or receipt write raises an error during installation, the tool attempts to restore the exact previous file contents and keeps the settings backup. It does not journal abrupt process or host termination between file replacements; after such an interruption, inspect settings, receipt, runtime, and backups before retrying. To restore a backup, first inspect the current settings and the backup; replace the whole file only when no later edits need to be kept. When later edits exist, manually merge only the entries you need from the backup.

## Uninstall

```sh
python3 tools/configure_language.py --uninstall
```

Uninstall removes only unchanged hook objects recorded in the local ownership receipt. It keeps later edits, foreign hooks, permissions, the copied script, receipts, per-session cache, diagnostics, and backups. If an owned hook has been edited, the edited object is preserved. The settings file must be a regular file no larger than 4 MB; symlinks, other file types, malformed hook structures, and oversized files are refused before configuration changes.

## Local event receipts

With `--state-dir` enabled, the hook appends a compact `[wf:<marker>]` to emitted language directives. The combined directive and marker stays within 98 characters. Each marker points to a signed, one-use local receipt that stores the supported event, timestamp, hashes of native IDs, result (`success` means the hook emitted its directive), and a version hash. A `SessionStart` receipt stores a null turn ID when Claude supplies none. The receipt never stores prompt text or raw native IDs. Consuming a receipt does not delete or invalidate the separate session cache.

To verify a marker, call the local `hook_receipt.verify` helper with the exact native `session_id`, `prompt_id` or `turn_id`, event name, marker, and version string. Compute that version string as `sha256(response_language_hook.py bytes + hook_receipt.py bytes).hexdigest()` from the installed files. Verification consumes the marker by default; do not verify it more than once. Receipt failures still emit the language directive and a bounded `systemMessage` stating that the receipt is unavailable; they never emit a fabricated marker.

A receipt verifies local file integrity and the supplied identity fields. It cannot authenticate that Claude Code originated those fields, prove causal native hook acceptance, or establish semantic language compliance. Native acceptance is host-specific; see the controlled sample below.

The hook also writes an optional metadata diagnostic in the same owner-only state directory. It keeps only a timestamp, supported event name, hashes of available native session/turn/prompt IDs, the combined hook-version hash, and a hash of the directive. Diagnostic write failures are ignored.

Review Claude Code's native hook settings and activation state after installation. Configuration and local tests alone do not establish runtime activation.

## Native controlled sample

A Claude Desktop Code Local test used the same neutral one-sentence English prompt, same subscription model and effort, and two isolated projects. Matching user/ancestor language instructions were excluded only in these fixtures, automatic memory was disabled there, and the visible context inspection showed the same neutral memory-file token count. The disabled control answered in English. The enabled control answered in Hebrew. The native SessionStart and UserPromptSubmit receipts were independently matched to the native session identity and separate workflow prompt metadata, verified against the installed script/helper digest, and consumed once. No model API or CLI was used.

After global installation, the temporary project handlers were removed. A later real prompt in the already-open test session produced exactly one global language receipt and no new project-local receipt. This is evidence of adoption in that tested existing Code Local session. It is a controlled sample of hook-caused language behavior, not a semantic guarantee for every future answer, not a Cowork result, and not a Codex or ordinary GPT result. Private identifiers, receipt keys, and raw evidence are not distributed.

A later cost optimization found a real semantic failure: an over-shortened declarative directive produced valid native receipts but an English response. The retained corrected imperative uses 40 characters for Hebrew and 43 for English; including the marker, the contexts are 95 and 98 characters. A fresh isolated native Hebrew sample with the identical neutral prompt then answered in Hebrew, and both native receipts were independently verified and consumed. The failed sample remains a failure, not a passing receipt-based inference. These samples show why a hook execution receipt must be checked separately from the requested behavior.

The session-cache version was also exercised through the native Desktop Code UI. In an already-open isolated session, the first prompt after the upgrade produced a verified success receipt; the next identical neutral prompt produced a verified skipped receipt and zero additional language context on that branch. A fresh isolated session produced a verified SessionStart success receipt and a UserPromptSubmit skipped receipt, and answered in Hebrew. A separate native metadata-only test callback captured the session and prompt IDs; each receipt was checked against those IDs and the installed script/helper version, then consumed. The callback added no model context and its temporary project registration was removed after testing. This establishes the tested cache lifecycle, not host delivery acknowledgement or universal response-language enforcement.

A later native Agent experiment exposed a remaining semantic failure with the current imperative and cache: signed SessionStart and cached UserPromptSubmit receipts were valid, but the parent answered in English. Loading is therefore proven for that sample while language compliance failed. Do not describe this hook as a deterministic output-language gate. Two UserPromptSubmit invocations with the same native identifiers were observed in that run; each had its own receipt, while only one language handler was registered. Their source cannot be inferred from an undocumented trigger field.
