#!/usr/bin/env python3
"""Bounded metadata-only observer for native Agent PostToolUse events."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time

MAX_INPUT = 1_000_000
MAX_FILE = 4_096
MAX_LABEL = 128
MAX_MODELS = 16
STATE_FILE = "latest-observation.json"
LOCK_FILE = ".delegation-observer.lock"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _string(value, label, limit=256):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"invalid {label}")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"invalid {label}")
    return value


def _native_ids(payload):
    session = _string(payload.get("session_id"), "session_id")
    prompt_id, turn_id = payload.get("prompt_id"), payload.get("turn_id")
    prompt_id = _string(prompt_id, "prompt_id") if prompt_id not in (None, "") else None
    turn_id = _string(turn_id, "turn_id") if turn_id not in (None, "") else None
    if prompt_id and turn_id and prompt_id != turn_id:
        raise ValueError("conflicting native turn IDs")
    turn = prompt_id or turn_id
    if not turn:
        raise ValueError("missing native turn ID")
    return session, turn, prompt_id is not None, _string(payload.get("tool_use_id"), "tool_use_id")


def _model(value, label):
    return None if value is None else _string(value, label, MAX_LABEL)


def _models(value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_MODELS:
        raise ValueError("invalid modelsUsed")
    return [_string(item, "modelsUsed item", MAX_LABEL) for item in value]


def _state_dir(value):
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError("owner-only state directory is required")
    path = Path(value).expanduser()
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise OSError("state directory must be owner-only and real")
    return path


@contextmanager
def _lock(state):
    fd = os.open(state / LOCK_FILE,
                 os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    locked = False
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size != 0):
            raise OSError("unsafe observer lock")
        deadline = time.monotonic() + 2.0
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("observer lock timed out")
                time.sleep(0.02)
        yield
    finally:
        if locked:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _write_observation(state, observation):
    target = state / STATE_FILE
    try:
        info = target.lstat()
    except FileNotFoundError:
        info = None
    if info is not None and (not stat.S_ISREG(info.st_mode)
                             or info.st_uid != os.getuid() or info.st_mode & 0o077
                             or info.st_size > MAX_FILE):
        raise OSError("unsafe observer state file")
    raw = json.dumps(observation, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True).encode("ascii")
    if len(raw) > MAX_FILE:
        raise ValueError("observer file exceeds size limit")
    fd, temp_name = tempfile.mkstemp(prefix=".delegation-observation-", dir=str(state))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _fingerprint():
    script = Path(__file__).read_bytes()
    receipt_helper = Path(__file__).with_name("hook_receipt.py").read_bytes()
    return hashlib.sha256(script + b"\0" + receipt_helper).hexdigest()


def _receipt_version(observation):
    canonical = json.dumps(observation, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True).encode("ascii")
    metadata_hash = hashlib.sha256(canonical).hexdigest()
    return f"{observation['hookFingerprint']}:{metadata_hash}"


def _skip(reason):
    return {"systemMessage": f"Agent observer skipped: {reason}"[:120]}


def run(payload, state_dir):
    """Record bounded metadata only; do not make permission or QA decisions."""
    if not isinstance(payload, dict):
        return _skip("invalid hook input.")
    if payload.get("hook_event_name", payload.get("event")) != "PostToolUse":
        return {}
    if payload.get("tool_name", payload.get("name")) != "Agent":
        return {}
    tool_input, response = payload.get("tool_input"), payload.get("tool_response")
    if not isinstance(tool_input, dict) or not isinstance(response, dict):
        return _skip("missing Agent metadata.")
    try:
        session, turn, is_prompt, tool_use_id = _native_ids(payload)
        status = response.get("status")
        if status not in {"completed", "async_launched"}:
            raise ValueError("unknown Agent status")
        prompt = tool_input.get("prompt")
        if prompt is not None and (not isinstance(prompt, str) or len(prompt) > MAX_INPUT):
            raise ValueError("invalid prompt")
        requested = _model(tool_input.get("model"), "requested model")
        resolved = _model(response.get("resolvedModel"), "resolvedModel")
        models_used = _models(response.get("modelsUsed"))
        agent_id = _string(response.get("agentId"), "agentId")
        fingerprint = _fingerprint()
        observation = {
            "schema": 1, "event": "PostToolUse", "tool": "Agent",
            "sessionHash": _hash(session), "turnHash": _hash(turn),
            "toolUseHash": _hash(tool_use_id),
            "promptHash": _hash(prompt) if prompt is not None else None,
            "requestedModel": requested, "resolvedModel": resolved,
            "modelsUsed": models_used, "status": status,
            "agentIdHash": _hash(agent_id), "hookFingerprint": fingerprint,
        }
        state = _state_dir(state_dir)
        with _lock(state):
            _write_observation(state, {"observation": observation, "receiptMarker": None})
            import hook_receipt
            identity = {"event": "PostToolUse", "session_id": session,
                        "prompt_id" if is_prompt else "turn_id": turn}
            marker, _receipt = hook_receipt.create(
                state, identity, "success", _receipt_version(observation))
            _write_observation(state, {"observation": observation, "receiptMarker": marker})
        if status == "async_launched":
            message = f"Agent launched; completion unverified. [wf:{marker}]"
        else:
            message = f"Agent metadata observed; task QA required. [wf:{marker}]"
        return {"systemMessage": message[:120]}
    except Exception as exc:
        # Never include event text, IDs, prompts, or tool output in diagnostics.
        return _skip(f"recording unavailable ({type(exc).__name__}).")


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--state-dir")
    args, _ = parser.parse_known_args(argv)
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError("oversized input")
        payload = json.loads(raw)
    except Exception:
        result = _skip("invalid or oversized hook input.")
    else:
        result = run(payload, args.state_dir)
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
