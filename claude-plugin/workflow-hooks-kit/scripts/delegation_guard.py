#!/usr/bin/env python3
"""Standalone native delegation prerequisite guard for an installed legacy kit core."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

MAX_INPUT = 1_000_000
MAX_MODEL_POLICY = 8_192
MAX_ORIGINAL_PROMPT = 32_768
DELEGATION_TOOLS = {"Agent", "spawn_agent"}
MODEL_ALIAS = re.compile(r"^\[workflow-stage:([1-9][0-9]*)\] ")


def _read_model_policy(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Model policy must be a regular owner-only file.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError("Model policy is missing, unreadable, or unsafe.") from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > MAX_MODEL_POLICY):
            raise ValueError("Model policy must be a bounded owner-only regular file.")
        chunks = []
        remaining = MAX_MODEL_POLICY + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 4096))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > MAX_MODEL_POLICY:
            raise ValueError("Model policy exceeds 8 KiB.")
        try:
            policy = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_unique_object)
        except UnicodeError as exc:
            raise ValueError("Model policy is not valid UTF-8.") from exc
        except json.JSONDecodeError as exc:
            raise ValueError("Model policy is not valid JSON.") from exc
    finally:
        os.close(fd)
    if type(policy) is not dict or set(policy) != {"schema", "models"}:
        raise ValueError("Model policy must contain exactly schema and models.")
    if type(policy["schema"]) is not int or policy["schema"] != 1:
        raise ValueError("Model policy schema must be integer 1.")
    models = policy["models"]
    if type(models) is not dict or not models or len(models) > 16:
        raise ValueError("Model policy must contain 1 to 16 aliases.")
    for alias, model_id in models.items():
        for label in (alias, model_id):
            if (not isinstance(label, str) or not label or len(label) > 256
                    or not label.isascii() or any(ch.isspace() or ord(ch) < 33 or ord(ch) == 127 for ch in label)):
                raise ValueError("Model aliases and native IDs must be bounded printable ASCII without whitespace.")
    return policy, raw


def _tool_name(payload):
    raw = payload.get("tool_name") or payload.get("name") or ""
    return str(raw).rsplit(".", 1)[-1]


def _is_delegation(payload):
    return (str(payload.get("hook_event_name") or payload.get("event") or "") == "PreToolUse"
            and _tool_name(payload) in DELEGATION_TOOLS)


def _deny(message):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": message[:300]}}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object keys are unsupported.")
        result[key] = value
    return result


def _native_ids(payload):
    session = payload.get("session_id")
    turn = payload.get("turn_id") or payload.get("prompt_id")
    return (isinstance(session, str) and bool(session.strip()) and len(session) <= 256
            and isinstance(turn, str) and bool(turn.strip()) and len(turn) <= 256
            and not any(ord(c) < 32 or ord(c) == 127 for c in session + turn))


def _runtime_version(core_dir: Path, model_policy=None, binding=None):
    script_dir = Path(__file__).absolute().parent
    paths = [script_dir / "delegation_guard.py", script_dir / "delegation_gate.py",
             script_dir / "hook_receipt.py", core_dir / "tool_scope_hook.py",
             core_dir / "session_workflow_hook.py"]
    if model_policy is not None:
        paths.append(script_dir / "delegation_binding.py")
    digest = hashlib.sha256()
    components = []
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Runtime component is missing or unsafe.")
        content = path.read_bytes()
        components.append((path, content))
        digest.update(content)
    if model_policy is None:
        return digest.hexdigest()
    strict_digest = hashlib.sha256()
    for path, content in components:
        name = path.name.encode("utf-8")
        strict_digest.update(len(name).to_bytes(4, "big"))
        strict_digest.update(name)
        strict_digest.update(len(content).to_bytes(8, "big"))
        strict_digest.update(content)
    strict_digest.update(b"model-policy.json\0")
    strict_digest.update(len(model_policy).to_bytes(8, "big"))
    strict_digest.update(model_policy)
    binding_bytes = json.dumps(dict(binding), ensure_ascii=False, allow_nan=False,
                               sort_keys=True, separators=(",", ":")).encode("utf-8", "strict")
    return strict_digest.hexdigest() + ":" + hashlib.sha256(binding_bytes).hexdigest()


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
    message = f"Delegation prerequisite gate evaluated; worker completion is not verified. {marker_text}"
    if isinstance(result, dict) and result:
        output = dict(result)
        existing = output.get("systemMessage")
        output["systemMessage"] = (str(existing) + " " + message).strip() if existing else message
        return output
    return {"systemMessage": message}


def _strict_input(ledger, tool_input, models):
    if type(tool_input) is not dict or set(tool_input) != {"description", "prompt", "model", "subagent_type"}:
        raise ValueError("Agent request fields do not match the supported native schema.")
    description, original_prompt = tool_input["description"], tool_input["prompt"]
    if not isinstance(description, str) or not description.strip() or len(description.encode("utf-8", "strict")) > 512:
        raise ValueError("Agent description must be bounded valid UTF-8 text.")
    if not isinstance(original_prompt, str) or len(original_prompt.encode("utf-8", "strict")) > MAX_ORIGINAL_PROMPT:
        raise ValueError("Original Agent prompt must be bounded valid UTF-8 text.")
    stages = ledger.get("stages")
    if type(stages) is not list or not stages or len(stages) > 20:
        raise ValueError("Ledger stages are missing or unsupported.")
    if len(stages) == 1:
        number = 1
        stage = stages[0]
    else:
        match = MODEL_ALIAS.match(description)
        if match is None:
            raise ValueError("Multi-stage description must select an exact workflow stage.")
        number = int(match.group(1))
        if number > len(stages):
            raise ValueError("Description selects a stage absent from this ledger.")
        stage = stages[number - 1]
        if description != f"[workflow-stage:{number}] {stage.get('name')}":
            raise ValueError("Description must exactly identify the selected frozen stage.")
    if type(stage) is not dict or type(stage.get("number")) is not int or stage.get("number") != number:
        raise ValueError("Selected frozen stage is malformed.")
    alias = tool_input["model"]
    if not isinstance(alias, str) or alias != stage.get("worker_model") or alias not in models:
        raise ValueError("Requested model must exactly match the selected stage and trusted alias policy.")
    from delegation_binding import build_prompt, validate_request
    candidate = dict(tool_input)
    candidate["description"] = f"[workflow-stage:{number}] {stage['name']}"
    candidate["prompt"] = build_prompt(stage)
    binding = validate_request(ledger, candidate, models)
    return candidate, binding


def _strict_tool_hash(payload):
    tool_use_id = payload.get("tool_use_id")
    if (not isinstance(tool_use_id, str) or not tool_use_id.strip() or len(tool_use_id) > 256
            or any(ord(char) < 32 or ord(char) == 127 for char in tool_use_id)):
        raise ValueError("Claude tool_use_id is missing or invalid.")
    return hashlib.sha256(tool_use_id.encode("utf-8", "strict")).hexdigest()


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


def run(payload, core_dir=None, claude=False, state_dir=None, model_map=None):
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
        denied = (isinstance(gate_result, dict) and isinstance(gate_result.get("hookSpecificOutput"), dict)
                  and gate_result["hookSpecificOutput"].get("permissionDecision") == "deny")
        if gate_result != {} and not denied:
            gate_result = _deny("Delegation prerequisite gate returned an invalid result; dispatch denied.")
            denied = True
        policy_raw = None
        binding = None
        if model_map is not None:
            if not claude:
                raise ValueError("Strict stage packets are supported only by the Claude hook contract.")
            policy, policy_raw = _read_model_policy(model_map)
            if gate_result == {}:
                _ledger_path, ledger = core._load_existing(payload, state)
                if not isinstance(ledger, dict):
                    raise ValueError("Matching active workflow ledger could not be reloaded.")
                candidate, binding = _strict_input(ledger, payload.get("tool_input"), policy["models"])
                binding = {"binding": dict(binding), "toolUseHash": _strict_tool_hash(payload)}
                gate_result = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": candidate},
                               "systemMessage": "Strict frozen-stage packet emitted; dispatch and worker completion are unverified."}
        version = _runtime_version(Path(core_dir).expanduser(), policy_raw, binding) if binding is not None else _runtime_version(Path(core_dir).expanduser())
        identity = {"event": "PreToolUse", "session_id": payload["session_id"]}
        if payload.get("turn_id"):
            identity["turn_id"] = payload["turn_id"]
        if payload.get("prompt_id"):
            identity["prompt_id"] = payload["prompt_id"]
        marker, _receipt = hook_receipt.create(state_dir, identity, "failure" if denied else "success", version)
        return _with_marker(gate_result, marker)
    except ValueError as exc:
        return _deny(f"Strict delegation validation denied the request: {exc}")
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
    parser.add_argument("--model-map")
    parser.add_argument("--claude", action="store_true")
    try:
        args, _ = parser.parse_known_args(argv)
        result = run(payload, args.core_dir, args.claude, args.state_dir, args.model_map)
    except Exception as exc:
        result = _deny(f"Delegation guard unavailable: {type(exc).__name__}; repair trusted core/task state before retrying.")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
