# Standalone delegation prerequisite guard

The standalone guard adds a separate `PreToolUse` handler for native `Agent` and `spawn_agent` calls beside an already installed legacy workflow core. It leaves the selected core files and existing hook groups untouched. The guard requires matching native session/turn identifiers, a protected project root, a valid frozen substantial plan, and an active task state. An unplanned delegation is denied until a substantial plan is saved through the existing workflow interface.

Install it with an explicit trusted core directory:

```sh
python3 -B tools/configure_delegation.py --platform codex --core-dir "$HOME/.codex/workflow-hooks-kit/bin"
python3 -B tools/configure_delegation.py --platform claude --core-dir "$HOME/.claude/workflow-hooks-kit/bin"
```

The installer copies `delegation_gate.py`, `delegation_guard.py`, and `hook_receipt.py` into a private `bin/delegation-guard/` directory, keeping other kit helpers independently owned. Receipts are kept in the owner-only `delegation-receipts/` state directory. Each marker records that the prerequisite check ran for the named native IDs; it does not mean a worker started or finished. The runtime digest covers the guard, gate, receipt helper, and selected legacy core/workflow bytes. Reruns are idempotent. Use `--uninstall` with the same platform and core directory to remove only the unchanged owned handler and unchanged files created by this installer. Receipt history and backups remain available. If an owned command or runtime was changed, the installer preserves it and refuses replacement/removal. An exact duplicate companion command or a selected core that already contains the gate causes installation to stop. Unrelated observer matchers are preserved alongside the gate.

When no ledger exists, the gate denies delegation without creating a ledger or other workflow record. Save a substantial plan through the existing `workflow-ledger plan '<JSON>'` interface, then retry. This keeps the gate read-only and allows the established planner to create a complete in-progress plan.

This is a prerequisite gate. It cannot authenticate that a payload came from the native host, prove a worker actually started, verify model identity, or certify completion or review. Existing observer hooks may match the same delegation events and run alongside this gate; their presence does not establish that a worker started. A local replay may exercise the check but is not evidence of native dispatch. Local tests and native activation are separate evidence.

Deployment proceeds in phases: (1) Codex and Claude Code gates plus native acceptance; (2) ordinary GPT capability assessment and implementation if supported; (3) Cowork. Evidence from the first phase does not certify later phases.

The dedicated executable rejects unreadable, oversized, non-object, or missing/invalid event and tool identities with a denial and no fabricated receipt. An explicitly identified unrelated tool remains a no-op. This does not compensate for a native host that never invokes the handler. A native Code Local negative sample observed one denied unprepared Agent call, no child result, no workflow ledger creation, and no corrective Stop turn. A repeated fresh first-prompt test of the current installed guard matched its single signed failure receipt to the exact native session ID from Desktop status and the raw prompt ID from separate legacy event metadata, verified the current runtime digest, and consumed the marker once. Neither a task ledger nor a Stop-continuation marker existed for that native turn. Positive native dispatch, actual model binding and Codex activation remain separate acceptance requirements.
