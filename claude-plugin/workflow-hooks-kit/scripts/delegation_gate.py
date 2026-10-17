#!/usr/bin/env python3
"""Shared prerequisite check for native worker-dispatch interception."""
from __future__ import annotations

DELEGATION_TOOLS = {"Agent", "spawn_agent"}


def check(core, payload: dict, state):
    """Return allow/deny for a native delegation tool using a loaded kit core."""
    event = core._event(payload)
    tool = core._tool_name(payload)
    if event != "PreToolUse" or tool not in DELEGATION_TOOLS:
        return {}
    try:
        sid, tid = core._ids(payload)
        if not sid or not tid:
            return core._deny(event, "Native session/turn ID missing; delegation requires an identified substantial plan.")
        ok, actual, root = core._protected_scope(payload, state)
        if not ok:
            return core._deny(event, str(actual)[:300])
        path, ledger = core._load_existing(payload, state)
        if path is not None and path.exists() and ledger is None:
            return core._deny(event, "Task ledger is invalid or mismatched; repair it before delegation.")
        if ledger is None:
            return core._deny(event, "Do not retry Agent until a substantial workflow-ledger plan with numbered stages is saved.")
        if ledger.get("task_kind") != "substantial":
            return core._deny(event, "Delegation requires a substantial plan with numbered stages, worker, DoD, outputs and checks.")
        if (type(ledger.get("schema_version")) is not int or ledger.get("schema_version") != 1
                or ledger.get("session_id") != sid or ledger.get("turn_id") != tid
                or core.workflow._root_hint(ledger.get("working_root")) != root):
            return core._deny(event, "Substantial ledger schema or protected identity is invalid; repair it before delegation.")
        if ledger.get("state") in {"complete", "blocked", "awaiting-user"}:
            return core._deny(event, "This task is terminal or blocked; resolve it in a new active turn before delegation.")
        try:
            valid = (core.workflow._plan_ready(ledger)
                     and core._plan_shape(core._prepared_plan_body(ledger)) == "substantial")
        except (ValueError, TypeError, KeyError, AttributeError):
            valid = False
        if not valid:
            return core._deny(event, "Prepare a substantial ledger: numbered stages, workers, DoD, outputs, qa.check and qa.expected; then retry.")
        if ledger.get("state") != "in-progress":
            return core._deny(event, "Substantial plan is not active; resume or prepare an active plan before delegation.")
        return {}
    except Exception as exc:
        return core._deny(event, f"Delegation gate unavailable: {type(exc).__name__}; repair task identity/state before retrying.")
