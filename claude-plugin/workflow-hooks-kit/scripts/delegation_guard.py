#!/usr/bin/env python3
"""Standalone native delegation prerequisite guard for an installed legacy kit core."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

MAX_INPUT = 1_000_000
DELEGATION_TOOLS = {"Agent", "spawn_agent"}


def _tool_name(payload):
    raw = payload.get("tool_name") or payload.get("name") or ""
    return str(raw).rsplit(".", 1)[-1]


def _is_delegation(payload):
    return (str(payload.get("hook_event_name") or payload.get("event") or "") == "PreToolUse"
            and _tool_name(payload) in DELEGATION_TOOLS)


def _deny(message):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": message[:300]}}


def _native_ids(payload):
    session = payload.get("session_id")
    turn = payload.get("turn_id") or payload.get("prompt_id")
    return (isinstance(session, str) and bool(session.strip()) and len(session) <= 256
            and isinstance(turn, str) and bool(turn.strip()) and len(turn) <= 256
            and not any(ord(c) < 32 or ord(c) == 127 for c in session + turn))


def _runtime_version(core_dir: Path):
    script_dir = Path(__file__).absolute().parent
    paths = [script_dir / "delegation_guard.py", script_dir / "delegation_gate.py",
             script_dir / "hook_receipt.py", core_dir / "tool_scope_hook.py",
             core_dir / "session_workflow_hook.py"]
    digest = hashlib.sha256()
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Runtime component is missing or unsafe.")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _with_marker(result, marker):
    marker_text = f"[wf:{marker}]"
    output = dict(result) if isinstance(result, dict) else {}
    detail = output.get("hookSpecificOutput")
    if isinstance(detail, dict) and detail.get("permissionDecision") == "deny":
        detail = dict(detail)
        reason = str(detail.get("permissionDecisionReason") or "Delegation prerequisite gate denied.")
        detail["permissionDecisionReason"] = (reason[:max(0, 300 - len(marker_text) - 1)] + " " + marker_text)[:300]
        output["hookSpecificOutput"] = detail
        return output
    return {"systemMessage": f"Delegation prerequisite gate evaluated; worker completion is not verified. {marker_text}"}


def _load_core(core_dir: Path):
    if core_dir.is_symlink() or not core_dir.is_dir():
        raise ValueError("Trusted core directory must be a real directory.")
    core_path = core_dir / "tool_scope_hook.py"
    workflow_path = core_dir / "session_workflow_hook.py"
    for path in (core_path, workflow_path):
        if path.is_symlink() or not path.is_file():
            raise ValueError("Trusted core and workflow files must be regular files.")
    sys.path.insert(0, str(core_dir))
    try:
        spec = importlib.util.spec_from_file_location("tool_scope_hook", core_path)
        if spec is None or spec.loader is None:
            raise ValueError("Could not load trusted workflow core.")
        module = importlib.util.module_from_spec(spec)
        sys.modules["tool_scope_hook"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        try:
            sys.path.remove(str(core_dir))
        except ValueError:
            pass


def run(payload, core_dir=None, claude=False, state_dir=None):
    if not isinstance(payload, dict) or not _is_delegation(payload):
        return {}
    if claude:
        prompt_id, turn_id = payload.get("prompt_id"), payload.get("turn_id")
        if isinstance(prompt_id, str) and prompt_id.strip():
            if turn_id not in (None, "", prompt_id):
                return _deny("Claude prompt_id and turn_id conflict; delegation was denied.")
            payload = dict(payload)
            payload["turn_id"] = prompt_id
    if claude:
        payload = dict(payload)
        payload["_claude_runtime"] = True
    if not _native_ids(payload):
        return _deny("Native session/turn IDs missing or invalid; delegation denied without a receipt.")
    try:
        import delegation_gate
        import hook_receipt
        if not isinstance(core_dir, (str, Path)) or not str(core_dir).strip():
            raise ValueError("Explicit trusted core directory is required.")
        core = _load_core(Path(core_dir).expanduser())
        state = core.CLAUDE_STATE if claude else core.workflow.STATE
        gate_result = delegation_gate.check(core, payload, state)
        if not isinstance(state_dir, (str, Path)) or not str(state_dir).strip():
            raise ValueError("Owner-only receipt state directory is required.")
        version = _runtime_version(Path(core_dir).expanduser())
        denied = (isinstance(gate_result, dict) and isinstance(gate_result.get("hookSpecificOutput"), dict)
                  and gate_result["hookSpecificOutput"].get("permissionDecision") == "deny")
        if gate_result != {} and not denied:
            gate_result = _deny("Delegation prerequisite gate returned an invalid result; dispatch denied.")
            denied = True
        identity = {"event": "PreToolUse", "session_id": payload["session_id"]}
        if payload.get("turn_id"):
            identity["turn_id"] = payload["turn_id"]
        if payload.get("prompt_id"):
            identity["prompt_id"] = payload["prompt_id"]
        marker, _receipt = hook_receipt.create(state_dir, identity, "failure" if denied else "success", version)
        return _with_marker(gate_result, marker)
    except Exception as exc:
        return _deny(f"Delegation guard unavailable: {type(exc).__name__}; repair trusted core/task state before retrying.")


def main(argv=None):
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        payload = json.loads(raw) if len(raw) <= MAX_INPUT else None
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        # This executable is registered only for delegation: unreadable input
        # cannot safely be interpreted as an unrelated tool invocation.
        print(json.dumps(_deny("Invalid or oversized delegation hook input; dispatch denied without a receipt.")))
        return 0
    event = payload.get("hook_event_name", payload.get("event"))
    tool = payload.get("tool_name", payload.get("name"))
    if any(not isinstance(value, str) or not value or value != value.strip()
           or len(value) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in value)
           for value in (event, tool)):
        print(json.dumps(_deny("Invalid delegation event/tool identity; dispatch denied without a receipt.")))
        return 0
    if not _is_delegation(payload):
        print("{}")
        return 0
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--core-dir")
    parser.add_argument("--state-dir")
    parser.add_argument("--claude", action="store_true")
    try:
        args, _ = parser.parse_known_args(argv)
        result = run(payload, args.core_dir, args.claude, args.state_dir)
    except Exception as exc:
        result = _deny(f"Delegation guard unavailable: {type(exc).__name__}; repair trusted core/task state before retrying.")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
