---
name: work-standards
description: Apply local planning, project scope, evidence, model cost and reversible hygiene standards when doing material work.
---

# Work standards

Use current user instructions and the host's permissions first. Complete authorized work autonomously. Ask only when a missing decision materially affects correctness or an explicit approval gate applies. Plan substantial work before mutation; use a compact plan for a small file change. Define outputs and an actual verification check before editing.

Load only a matching approved scope through the optional learning CLI with `read --scope <matching-scope>`. Do not directly read generated standards files: the CLI checks their approval against local state and rejects pending or orphaned blocks. Default learning state is `~/.local/share/workflow-hooks-kit/learning/`; use an explicitly supplied `--state-dir` for another profile. This state belongs to the current runtime environment and may not be visible in a remote VM. If the CLI or local state is unavailable, use this base policy. There is no automatic synchronization, transcript scanning, or full-profile read on each prompt.

## Workflow ledger

Inside a native hooked Bash tool call, submit `workflow-ledger plan '<JSON>'` or `workflow-ledger qa '<JSON>'` as an exact standalone command. These are sentinels intercepted by the PreToolUse hook, not installed executables. A denial reporting that the plan or QA was saved is expected; it prevents the sentinel reaching the shell. If hooks are unavailable, keep an ordinary written plan and evidence; do not repeatedly execute the sentinel in a terminal.

A compact plan requires `definition_of_done`, `outputs`, and `qa` with `check` and `expected`. Run the actual check, then submit QA with `state: complete`, `evidence`, `verdict: pass`, and `reviewer_id: lead`. Substantial plans use numbered stages with worker declarations, inputs, boundaries and dependencies; each stage needs a reviewer distinct from its declared worker. Declarations are not proof of which model or person performed work.

Keep edits within the established project root or explicitly approved allowed roots. Shell commands are only partly observable; unknown effects require review. Do not claim generic MCP writes are protected. Preserve required rollback copies. Move reviewed obsolete material to the same project's `Old/YYYY-MM/` with collision protection and a recovery manifest. Never delete history or archive based only on names.

Use the cheapest adequate model actually available, with a stated rationale. After three failed attempts on one declared model, reassess and escalate through the explicitly available model order or return the blocker. Hooks validate recorded attempts; they cannot switch models, schedule agents or enforce real execution counts.

Verify outputs against the definition of done and report concrete evidence. Do not change a failed verdict without new checks. Record `blocked` with a blocker or `awaiting-user` with a question when completion is impossible. Optional file assertions verify actual small local files. A one-time Stop block asks for correction; subsequent stops avoid an infinite loop and do not constitute a pass.

Save useful lessons through the optional local learning CLI only with authorized source material. Global installs provide `~/.codex/workflow-hooks-kit/bin/learning_cli.py` or `~/.claude/workflow-hooks-kit/bin/learning_cli.py`. Packaged plugins provide `${CLAUDE_PLUGIN_ROOT}/learning/cli.py`; directory-loaded clones use the repository `learning/cli.py`. Invoke the CLI with Python and use `read --scope <matching-scope>`; approve proposals only with explicit user authorization. Total Recall is an optional separate integration, not bundled or installed by this kit. Never imply recall or cloud standards are active without evidence.

## Opt-in strict hygiene

When the operator has enabled strict hygiene, do not substitute written review for the executable gate. In a native hooked shell call use `workflow-hygiene inspect '{"paths":["relative/path"]}'`, then `workflow-hygiene review '<JSON>'`. Each review entry requires path, decision (keep/asset/archive/uncertain), actual sha256 or null for absence, reason, usage, dependencies and concurrency. A denial saying inspection/review was accepted is sentinel interception, not shell failure. Inspect alone grants no approval. Obtain preflight before each supported edit, preserve old bytes, and submit post-edit review before another edit or Stop. Resolve uncertainty with the user. Preserve required code/config locations; helpers belong in Assets when safe. Strict mode rejects unverified shell writes. Archive and restore require code checks; full semantic dependencies and arbitrary host/MCP paths remain unproven. Read the package hygiene-enforcement documentation before enabling this restriction in a build workflow.
