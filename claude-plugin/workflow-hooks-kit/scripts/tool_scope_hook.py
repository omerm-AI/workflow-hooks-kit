#!/usr/bin/env python3
"""Fail-open tool-boundary scope checks and metadata-only touched-path ledger adapter."""
from __future__ import annotations
import argparse
import copy
from datetime import datetime
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
import stat
import time
import tempfile
from typing import Any

try:
    import session_workflow_hook as workflow
    import delegation_gate
except Exception:
    sys.stderr.write("Hook dependency unavailable; action not authorized.\n")
    raise SystemExit(2)

MAX_INPUT = 1_000_000
MAX_BODY = 32_768
MAX_PATHS = 200
MAX_ALLOWED_ROOTS = 8
MAX_PATH_CHARS = 4096
MAX_LEDGER = workflow.MAX_LEDGER
CLAUDE_STATE = Path.home() / ".claude" / "workflow-hooks-kit"
EDIT_TOOLS = {"Edit", "Write", "apply_patch", "NotebookEdit", "MultiEdit"}
DELEGATION_TOOLS = delegation_gate.DELEGATION_TOOLS
RG_FLAGS = {"--no-config", "--files", "--hidden", "--no-ignore", "--no-ignore-vcs", "--no-messages", "--line-number", "--files-with-matches", "--files-without-match", "--count", "--count-matches", "--ignore-case", "--fixed-strings", "--word-regexp", "--invert-match", "--only-matching", "--json", "--stats", "--quiet", "--no-heading", "--heading", "--with-filename", "--no-filename", "-n", "-l", "-L", "-c", "-i", "-F", "-w", "-v", "-o", "-q"}
RG_VALUES = {"--glob", "--iglob", "--regexp", "--file", "--max-count", "--max-depth", "--type", "--type-not", "--context", "--before-context", "--after-context", "--color", "-g", "-e", "-f", "-m", "-t", "-T", "-C", "-B", "-A"}
PATCH_PATH = re.compile(r"^[ \t]*\*\*\*[ \t]+(?:(?:Add|Update|Delete)[ \t]+File|Move[ \t]+to):[ \t]*(.*?)[ \t]*$", re.M)


def _event(p: dict[str, Any]) -> str:
    return str(p.get("hook_event_name") or p.get("event") or "")


def _tool_name(p: dict[str, Any]) -> str:
    raw = p.get("tool_name") or p.get("name") or ""
    return str(raw).rsplit(".", 1)[-1]


def _input(p: dict[str, Any]) -> dict[str, Any]:
    value = p.get("tool_input")
    return value if isinstance(value, dict) else {}


def _ids(p: dict[str, Any]) -> tuple[str | None, str | None]:
    sid = p.get("session_id")
    tid = p.get("turn_id") or p.get("prompt_id")
    return (sid if isinstance(sid, str) and sid.strip() else None,
            tid if isinstance(tid, str) and tid.strip() else None)


def _root(p: dict[str, Any]) -> tuple[bool, str]:
    return workflow._valid_cwd(p.get("cwd"))


def _deny(event: str, text: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": event, "permissionDecision": "deny", "permissionDecisionReason": text}}


def _patch_paths(value: Any) -> list[str]:
    if not isinstance(value, str) or len(value) > MAX_INPUT:
        return []
    # Keep one overflow sentinel so callers deny rather than silently omit targets.
    return [m.group(1).strip() for m in PATCH_PATH.finditer(value) if m.group(1).strip()][:MAX_PATHS + 1]


def _input_paths(tool: str, data: dict[str, Any]) -> list[str]:
    if tool == "apply_patch":
        return _patch_paths(data.get("command") or data.get("patch") or data.get("input"))
    raw = data.get("notebook_path") if tool == "NotebookEdit" else data.get("file_path") or data.get("path") or data.get("target_file")
    return [raw] if isinstance(raw, str) and raw.strip() else []


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _load_existing(p: dict[str, Any], state: Path) -> tuple[Path | None, dict[str, Any] | None]:
    sid, tid = _ids(p)
    if not sid or not tid:
        return None, None
    original = workflow.STATE
    try:
        workflow.STATE = state
        path = workflow._ledger_path(sid, tid)
    except Exception:
        return None, None
    finally:
        workflow.STATE = original
    if not path.exists():
        return path, None
    try:
        data = workflow._read(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return path, None
    if data.get("session_id") != sid or data.get("turn_id") != tid:
        return path, None
    return path, data


def _roots(p: dict[str, Any], ledger: dict[str, Any] | None, root: str) -> list[Path]:
    # Model-authored metadata cannot authorize filesystem roots.
    return [Path(root).resolve()]


def _resolve_target(raw: str, root: Path) -> Path:
    expanded = Path(raw).expanduser()
    if not expanded.is_absolute():
        expanded = root / expanded
    return expanded.resolve(strict=False)


def _validate_targets(event: str, raw_paths: list[str], root: str, ledger: dict[str, Any] | None, resolve_root: str | None = None) -> dict[str, Any] | None:
    base = Path(resolve_root or root).resolve()
    allowed = _roots({}, ledger, root)
    if not raw_paths:
        return _deny(event, "קובץ היעד חסר או לא ניתן לזיהוי. יש לציין יעד מפורש בתוך תיקיית העבודה.")
    if len(raw_paths) > MAX_PATHS:
        return _deny(event, "מספר קובצי היעד חורג ממגבלת הבדיקה הבטוחה.")
    for raw in raw_paths[:MAX_PATHS]:
        if len(raw) > MAX_PATH_CHARS or "\x00" in raw:
            return _deny(event, "נתיב הקובץ אינו תקין או ארוך מדי.")
        try:
            target = _resolve_target(raw, base)
        except (OSError, RuntimeError, ValueError):
            return _deny(event, "לא ניתן לאמת את נתיב קובץ היעד.")
        if not any(_inside(target, allowed_root) for allowed_root in allowed):
            return _deny(event, "קובץ היעד מחוץ לתיקיית העבודה; שורשים ביומן אינם מעניקים הרשאה.")
    return None


def _readonly_bash(command: Any) -> bool:
    if not isinstance(command, str) or len(command) > MAX_INPUT:
        return False
    # Parse arguments only after ruling out shell expansion, execution and redirection.
    if any(character in command for character in "$`;&|<>\n\r()"):
        return False
    try:
        args = shlex.split(command, comments=False, posix=True)
    except ValueError:
        return False
    if not args:
        return False
    if args[0] == "pwd":
        return len(args) == 1
    if args[0] == "cat":
        return len(args) > 1 and all(arg and not arg.startswith("-") for arg in args[1:])
    if args[:2] == ["git", "status"]:
        return all(arg in {"--short", "--branch", "-sb", "--porcelain"} for arg in args[2:])
    if args[0] == "rg":
        flags, values = RG_FLAGS, RG_VALUES
    elif args[0] == "ls":
        flags = {"-l", "-a", "-A", "-la", "-al", "-lh", "-lah", "-ahl", "-1", "-d", "-h", "--all", "--almost-all", "--directory"}
        values = {"--color"}
    elif args[0] in {"head", "tail"}:
        flags, values = {"-q", "-v", "--quiet", "--verbose"}, {"-n", "-c", "--lines", "--bytes"}
    elif args[0] == "wc":
        flags, values = {"-l", "-w", "-c", "-m", "-L", "--lines", "--words", "--bytes", "--chars", "--max-line-length"}, set()
    elif args[0] == "grep":
        flags = {"-n", "-i", "-v", "-F", "-E", "-l", "-L", "-c", "-h", "-H", "-q", "-s", "-r", "-R", "-w", "-x", "--line-number", "--ignore-case", "--fixed-strings", "--extended-regexp", "--quiet"}
        values = {"-e", "-f", "-A", "-B", "-C", "-m", "--regexp", "--file", "--color", "--max-count"}
    else:
        return False
    index = 1
    while index < len(args):
        arg = args[index]
        if arg == "--":
            return True
        if arg.startswith("-"):
            option, separator, value = arg.partition("=")
            if option in flags and not separator:
                pass
            elif option in values:
                if separator:
                    if not value:
                        return False
                else:
                    index += 1
                    if index >= len(args) or args[index].startswith("-"):
                        return False
            else:
                return False
        index += 1
    return True


def _has_acceptance_plan(ledger: dict[str, Any] | None) -> bool:
    return workflow._plan_ready(ledger)


def _ensure_ledger(p, state, root, kind="small"):
    sid, tid = _ids(p)
    if not sid or not tid:
        return None, None
    _state_dir(state)
    path = state / (hashlib.sha256((sid + "\0" + tid).encode()).hexdigest() + ".json")
    with _ledger_lock(path):
        original = workflow.STATE
        try:
            workflow.STATE = state
            workflow.start_task({"session_id": sid, "turn_id": tid, "cwd": root, **({"agent_id": p["agent_id"]} if p.get("agent_id") else {})}, kind)
        finally:
            workflow.STATE = original
        if path.is_symlink():
            return path, None
        try:
            ledger = workflow._read(path)
        except ValueError:
            return path, None
        if ledger.get("session_id") != sid or ledger.get("turn_id") != tid:
            return path, None
    return path, ledger


def _prepare_message(path):
    # The native model may not have loaded project rules; provide typed JSON.
    return "Before editing, submit Bash: workflow-ledger plan '{\"definition_of_done\":\"required result\",\"outputs\":[\"relative/file\"],\"qa\":{\"check\":\"actual check\",\"expected\":\"required result\"}}'. Replace values. Hook denial saying saved means accepted. Or workflow-ledger continue."


def _parse_ledger_command(command):
    if not isinstance(command, str): return None
    prefix = bool(re.match(r"^\s*[\'\"]?workflow-ledger", command))
    if len(command) > MAX_INPUT:
        return ("error", "Ledger command exceeds the input limit.") if prefix else None
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>$`()\n\r")
        lexer.whitespace_split, lexer.commenters = True, ""
        args = list(lexer)
    except ValueError:
        return ("error", "Malformed quoted ledger command; escape apostrophes and quote JSON as one shell argument.") if prefix else None
    if args and "workflow-ledger" in args and args[0] != "workflow-ledger":
        return "error", "Use workflow-ledger as an exact standalone command; no cd, environment assignment or chained command prefixes."
    if not args or args[0] != "workflow-ledger":
        return ("error", "Malformed ledger command prefix.") if prefix else None
    if args == ["workflow-ledger", "start", "substantial"]: return "start", None
    if args == ["workflow-ledger", "continue"]: return "continue", None
    if len(args) == 3 and args[1] == "repair-legacy":
        turn = args[2]
        if not turn.strip() or turn != turn.strip() or len(turn.encode("utf-8")) > 256 or "\0" in turn:
            return "error", "repair-legacy requires one exact previous native turn ID, at most 256 bytes."
        return "repair-legacy", turn
    if len(args) != 3 or args[1] not in {"plan", "qa", "replace-carried-plan"}:
        return "error", "Use exact workflow-ledger start substantial, continue, plan '<JSON>', or qa '<JSON>'; shell operators are not allowed."
    if len(args[2].encode("utf-8")) > MAX_BODY: return "error", "Ledger JSON exceeds 32 KB."
    try:
        body = json.loads(args[2])
    except ValueError:
        return "error", "Ledger body must be one quoted JSON object."
    if not isinstance(body, dict): return "error", "Ledger body must be a JSON object."
    return args[1], body


def _ledger_command(command):
    parsed = _parse_ledger_command(command)
    return parsed[0] if parsed and parsed[0] != "error" else None


def _declaration_bash(command):
    return _ledger_command(command) == "start"


def _nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def _plan_shape(body):
    if set(body) == {"definition_of_done", "outputs", "qa"}:
        kind, stages = "small", [body]
    elif set(body) == {"stages"}:
        kind, stages = "substantial", body["stages"]
        if not isinstance(stages, list) or not stages or len(stages) > workflow.MAX_STAGES:
            raise ValueError("Plan requires 1-20 stages.")
    else:
        raise ValueError("Plan fields must be DoD/outputs/qa, or stages; protected and unknown fields are rejected.")
    names = set()
    for number, stage in enumerate(stages, 1):
        required = {"definition_of_done", "outputs", "qa"}
        if kind == "substantial":
            required |= {"number", "name", "worker_id", "worker_model", "worker_effort", "model_rationale", "inputs", "boundaries", "dependencies"}
        if not isinstance(stage, dict) or set(stage) != required:
            raise ValueError("Plan stage has missing, protected or unknown fields.")
        if not _nonblank(stage["definition_of_done"]) or not workflow._valid_outputs(stage["outputs"]):
            raise ValueError("Plan requires nonblank DoD and output strings.")
        qa = stage["qa"]
        if (not isinstance(qa, dict) or not {"check", "expected"} <= set(qa)
                or set(qa) - {"check", "expected", "assertions"}
                or any(not _nonblank(qa[key]) for key in ("check", "expected"))):
            raise ValueError("Plan QA accepts nonblank check/expected and optional literal assertions.")
        if "assertions" in qa: workflow._assertions_shape(qa["assertions"], stage["outputs"])
        if kind == "substantial":
            if isinstance(stage["number"], bool) or stage["number"] != number or not isinstance(stage["number"], int):
                raise ValueError("Plan stage numbers must be consecutive integers.")
            for key in ("name", "worker_id", "worker_model", "worker_effort", "model_rationale"):
                if not _nonblank(stage[key]): raise ValueError("Plan worker/stage labels must be nonblank.")
            if stage["name"] in names: raise ValueError("Plan stage names must be unique.")
            names.add(stage["name"])
            if stage["worker_effort"] not in {"low", "medium", "high", "xhigh", "max", "ultra", "minimal", "none"}:
                raise ValueError("Plan worker effort is unsupported.")
            if any(not isinstance(stage[key], list) or any(not isinstance(item, str) for item in stage[key]) for key in ("inputs", "boundaries", "dependencies")):
                raise ValueError("Plan inputs, boundaries and dependencies must be string lists.")
    return kind


def _prepared_plan_body(ledger):
    def phase(stage, substantial=False):
        keys = {"definition_of_done", "outputs"}
        if substantial:
            keys |= {"number", "name", "worker_id", "worker_model", "worker_effort", "model_rationale", "inputs", "boundaries", "dependencies"}
        result = {key: copy.deepcopy(stage.get(key)) for key in keys}
        qa = stage.get("qa", {})
        result["qa"] = {key: qa.get(key) for key in ("check", "expected")}
        if "assertions" in qa: result["qa"]["assertions"] = copy.deepcopy(qa["assertions"])
        return result
    if ledger.get("task_kind") == "small":
        stage = ledger if any(key in ledger for key in ("definition_of_done", "outputs", "qa")) else ledger["stages"][0]
        return phase(stage)
    return {"stages": [phase(stage, True) for stage in ledger["stages"]]}


def _qa_update(existing, update):
    if not isinstance(update, dict) or not update or set(update) - {"evidence", "verdict", "reviewer_id"}:
        raise ValueError("QA updates accept evidence, verdict and reviewer_id only; check/expected/assertions are immutable.")
    if any(not _nonblank(value) for value in update.values()): raise ValueError("QA values must be nonblank strings.")
    if update.get("verdict") == "pass" and not {"evidence", "reviewer_id"} <= set(update):
        raise ValueError("PASS requires fresh evidence and reviewer_id in the same QA update.")
    if "verdict" in update and update["verdict"] not in {"pass", "fail", "blocked", "pending"}:
        raise ValueError("QA verdict is unsupported.")
    result = copy.deepcopy(existing) if isinstance(existing, dict) else {}
    result.update(update)
    return result


def _compatible_record(ledger):
    """Version-one adapter: numeric dependencies name earlier numbered stages."""
    inferred = "task_kind" not in ledger
    kind = ledger.get("task_kind", "substantial")
    if not isinstance(kind, str) or kind not in {"small", "substantial"}:
        raise ValueError("Unsupported task_kind. Preserve this ledger and review its schema before retrying.")
    candidate = copy.deepcopy(ledger)
    if inferred:
        candidate["task_kind"] = "substantial"
        stages = candidate.get("stages")
        if not isinstance(stages, list) or not stages:
            raise ValueError("Legacy plan invalid; preserve this ledger and review its missing stages.")
        for stage in stages:
            if not isinstance(stage, dict) or not isinstance(stage.get("dependencies"), list):
                raise ValueError("Legacy plan invalid; preserve this ledger and review stage dependencies.")
            number = stage.get("number")
            references = []
            for dependency in stage["dependencies"]:
                if isinstance(dependency, str):
                    references.append(dependency)
                elif (isinstance(dependency, int) and not isinstance(dependency, bool)
                        and isinstance(number, int) and not isinstance(number, bool)
                        and 1 <= dependency < number):
                    references.append("stage:" + str(dependency))
                else:
                    raise ValueError("Legacy dependency invalid; only exact earlier integer stage references can migrate. Preserve the ledger.")
            stage["dependencies"] = references
    compact = any(key in candidate for key in ("definition_of_done", "outputs", "qa"))
    stages = candidate.get("stages")
    if kind == "substantial" and compact:
        raise ValueError("Conflicting substantial/compact fields. Preserve this ledger and review its schema.")
    if kind == "small" and not compact and not (isinstance(stages, list) and len(stages) == 1):
        if not (stages == [] and candidate.get("state") == "awaiting-plan"):
            raise ValueError("Conflicting small/stage fields. Preserve this ledger and review its schema.")
    blank = not inferred and not compact and stages == [] and candidate.get("state") == "awaiting-plan"
    if not blank:
        try:
            frozen = _prepared_plan_body(candidate)
            # Known schemas retain assertion binding as a real QA gate, not a
            # migration/schema error. Validate literal schema before removing
            # assertions from this temporary structural-only projection.
            if not inferred:
                phases = [frozen] if kind == "small" else frozen["stages"]
                for phase in phases:
                    qa = phase["qa"]
                    if "assertions" in qa:
                        assertions = qa["assertions"]
                        targets = [item.get("path") for item in assertions if isinstance(item, dict)] if isinstance(assertions, list) else []
                        workflow._assertions_shape(assertions, targets)
                        qa.pop("assertions")
            if _plan_shape(frozen) != kind: raise ValueError("Conflicting plan kind.")
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ValueError("Existing plan invalid; no criteria changed. Preserve this ledger and review stage/QA schema before retrying.") from exc
    return candidate, inferred


def _backup_legacy(path, label="legacy-schema1-kind-v1"):
    """Retain exact pre-migration bytes privately; failure precedes any ledger write."""
    archive = path.parent
    for part in ("Old", datetime.now().astimezone().strftime("%Y-%m")):
        archive = archive / part
        if archive.is_symlink(): raise ValueError("Legacy backup folder is a symlink; ledger unchanged.")
        archive.mkdir(exist_ok=True, mode=0o700)
        if not archive.is_dir(): raise ValueError("Legacy backup folder unavailable; ledger unchanged.")
    original_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(original_fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Legacy record is not regular; ledger unchanged.")
        raw = stream.read(MAX_LEDGER + 1)
    if len(raw) > MAX_LEDGER: raise ValueError("Legacy record exceeds bounded size; ledger unchanged.")
    backup = archive / (path.stem + "." + label + "-" + str(time.time_ns()) + ".json")
    fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return backup


def _migrate_current(p, state, root):
    """Sentinel start/continue compatibility uses only the exact current native record."""
    sid, tid = _ids(p)
    if not sid or not tid: raise ValueError("Native identifiers required; no migration performed.")
    path = state / (hashlib.sha256((sid + "\0" + tid).encode()).hexdigest() + ".json")
    if not path.exists(): return
    with _ledger_lock(path):
        record = workflow._read(path)
        if (type(record.get("schema_version")) is not int or record.get("schema_version") != 1 or record.get("session_id") != sid
                or record.get("turn_id") != tid or workflow._root_hint(record.get("working_root")) != root):
            raise ValueError("Current ledger native identity/project does not match.")
        record, inferred = _compatible_record(record)
        if inferred:
            _backup_legacy(path)
            _atomic_write(path, record)


def _repair_previous_legacy(p, state, root, previous_turn):
    """Explicit maintenance target; native current SID/root cannot be overridden."""
    sid, tid = _ids(p)
    if not sid or not tid: raise ValueError("Native session/turn identifiers required.")
    if previous_turn == tid: raise ValueError("repair-legacy requires a previous turn, never the current record.")
    _state_dir(state)
    path = state / (hashlib.sha256((sid + "\0" + previous_turn).encode()).hexdigest() + ".json")
    if not path.exists(): raise ValueError("Exact previous native record is missing; no record changed.")
    with _ledger_lock(path):
        record = workflow._read(path)
        if (type(record.get("schema_version")) is not int or record.get("schema_version") != 1 or record.get("session_id") != sid
                or record.get("turn_id") != previous_turn or workflow._root_hint(record.get("working_root")) != root):
            raise ValueError("Previous record identity/project/schema differs; no record changed.")
        if "task_kind" in record: raise ValueError("Previous record is not missing legacy task_kind; no record changed.")
        repaired, inferred = _compatible_record(record)
        if not inferred: raise ValueError("No supported legacy repair required; no record changed.")
        _backup_legacy(path)
        _atomic_write(path, repaired)
    return "Legacy record repaired with exact backup; state, QA, criteria and native identity preserved. Current record and continuity index unchanged. No PASS claimed."


def _replace_carried_plan(p, state, root, body):
    """Explicitly replace only a blocked carried plan, retaining its exact history."""
    sid, tid = _ids(p)
    if not sid or not tid: raise ValueError("Native session/turn identifiers required.")
    kind = _plan_shape(body)
    _state_dir(state)
    path = state / (hashlib.sha256((sid + "\0" + tid).encode()).hexdigest() + ".json")
    if not path.exists(): raise ValueError("No current carried plan exists; save a normal plan instead.")
    with _ledger_lock(path):
        old = workflow._read(path)
        if (type(old.get("schema_version")) is not int or old.get("schema_version") != 1 or old.get("session_id") != sid or old.get("turn_id") != tid
                or workflow._root_hint(old.get("working_root")) != root):
            raise ValueError("Current record identity/project/schema differs; no record changed.")
        carried = old.get("carried_from")
        if (not _nonblank(carried) or carried == tid or old.get("state") != "blocked"
                or not _nonblank(old.get("blocker"))):
            raise ValueError("Replacement requires a carried plan explicitly blocked with blocker. Use qa to record the wrong-task blocker first.")
        _compatible_record(old)
        candidate = workflow._new_ledger(sid, tid, old["working_root"], kind)
        candidate.update(copy.deepcopy(body))
        for stage in [candidate] if kind == "small" else candidate["stages"]:
            stage["qa"].update(verdict="pending", evidence="pending", reviewer_id="")
        candidate["state"] = "in-progress"
        if p.get("agent_id"): candidate["source_agent_id"] = str(p["agent_id"])[:256]
        encoded = json.dumps(candidate, ensure_ascii=False, indent=2).encode("utf-8")
        if len(encoded) > MAX_LEDGER: raise ValueError("New plan exceeds bounded record size; no record changed.")
        backup = _backup_legacy(path, "blocked-carried-plan-v1")
        candidate["replaced_carried_plan_backup"] = backup.name
        candidate["replaced_carried_from"] = carried
        _atomic_write(path, candidate)
    if not p.get("agent_id"):
        original = workflow.STATE
        try:
            workflow.STATE = state
            workflow._register_active(sid, tid, path)
        finally: workflow.STATE = original
    return "Blocked carried plan archived exactly; new frozen plan saved with pending QA. Do work/checks, then workflow-ledger qa '<JSON>'. No PASS claimed."


def _apply_api(p, state, root, action, body):
    sid, tid = _ids(p)
    if not sid or not tid: raise ValueError("Native session/turn identifiers are required.")
    kind = _plan_shape(body) if action == "plan" else None
    if action == "qa" and (not body or set(body) - {"state", "blocker", "question", "qa", "stages"}):
        raise ValueError("QA contains unknown or protected fields.")
    _state_dir(state)
    path = state / (hashlib.sha256((sid + "\0" + tid).encode()).hexdigest() + ".json")
    with _ledger_lock(path):
        if path.exists():
            ledger = workflow._read(path)
            if type(ledger.get("schema_version")) is not int or ledger.get("schema_version") != 1 or ledger.get("session_id") != sid or ledger.get("turn_id") != tid or workflow._root_hint(ledger.get("working_root")) != root:
                raise ValueError("Current ledger native identity/project does not match.")
        elif action == "plan":
            ledger = workflow._new_ledger(sid, tid, root, kind)
            if p.get("agent_id"): ledger["source_agent_id"] = str(p["agent_id"])[:256]
        else:
            raise ValueError("Save a plan before QA; no current native ledger exists.")
        ledger, inferred_kind = _compatible_record(ledger)
        if action == "plan" and workflow._plan_ready(ledger):
            if body != _prepared_plan_body(ledger):
                raise ValueError("Prepared plan is immutable: DoD, outputs, workers, dependencies and QA criteria cannot be rewritten.")
            if inferred_kind:
                _backup_legacy(path)
                _atomic_write(path, ledger)
            return "Plan already saved; identical request changed no criteria, QA evidence, state or attempts. Continue work/checks, then record workflow-ledger qa '<JSON>'."
        candidate = copy.deepcopy(ledger)
        if action == "plan":
            if candidate.get("task_kind") != kind:
                upgrade = (candidate.get("task_kind") == "small" and kind == "substantial" and candidate.get("state") == "awaiting-plan" and not workflow._plan_ready(candidate) and not candidate.get("touched_paths") and not candidate.get("tool_effect_uncertain"))
                if not upgrade: raise ValueError("Prepared/material task kind cannot be changed.")
                candidate["task_kind"] = kind
            if kind == "small":
                legacy = candidate.get("stages")
                if "attempts" not in candidate and isinstance(legacy, list) and len(legacy) == 1 and isinstance(legacy[0], dict) and "attempts" in legacy[0]:
                    candidate["attempts"] = legacy[0]["attempts"]
                candidate.update(copy.deepcopy(body))
                candidate["stages"] = []
            else:
                old = {stage.get("number"): stage for stage in candidate.get("stages", []) if isinstance(stage, dict)}
                candidate["stages"] = copy.deepcopy(body["stages"])
                for stage in candidate["stages"]:
                    if "attempts" in old.get(stage["number"], {}): stage["attempts"] = old[stage["number"]]["attempts"]
            for stage in [candidate] if kind == "small" else candidate["stages"]:
                stage["qa"].update(verdict="pending", evidence="pending", reviewer_id="")
            candidate["state"] = "in-progress"
            candidate.pop("allowed_roots", None)
            message = 'Plan saved. Retry edit; run the actual check. Then workflow-ledger qa \'{"state":"complete","qa":{"evidence":"<what you ran/saw>","verdict":"pass","reviewer_id":"lead"}}\'. PASS needs fresh evidence; on failure fix/retest or use blocked/awaiting-user.' if kind == "small" else 'Plan saved. Do work; run actual checks. Then workflow-ledger qa \'{"state":"complete","stages":[{"number":1,"qa":{"evidence":"<actual result>","verdict":"pass","reviewer_id":"<independent reviewer>"}}]}\'. Repeat each stage; no PASS without fresh evidence.'
        else:
            if "qa" in body:
                if candidate.get("task_kind") != "small" or "stages" in body: raise ValueError("Root QA updates require a small task.")
                target = candidate
                if not any(key in candidate for key in ("definition_of_done", "outputs", "qa")):
                    legacy = candidate.get("stages")
                    if isinstance(legacy, list) and len(legacy) == 1 and isinstance(legacy[0], dict): target = legacy[0]
                target["qa"] = _qa_update(target.get("qa"), body["qa"])
            if "stages" in body:
                if candidate.get("task_kind") != "substantial" or not isinstance(body["stages"], list) or not body["stages"]:
                    raise ValueError("Numbered stage QA updates require a substantial task.")
                stages = {stage.get("number"): stage for stage in candidate.get("stages", []) if isinstance(stage, dict)}
                seen = set()
                for update in body["stages"]:
                    if not isinstance(update, dict) or set(update) != {"number", "qa"} or not isinstance(update["number"], int) or isinstance(update["number"], bool) or update["number"] not in stages or update["number"] in seen:
                        raise ValueError("Stage QA requires unique existing integer stage numbers.")
                    seen.add(update["number"])
                    stage = stages[update["number"]]
                    stage["qa"] = _qa_update(stage.get("qa"), update["qa"])
            for key in ("state", "blocker", "question"):
                if key in body:
                    if not _nonblank(body[key]): raise ValueError("QA state/blocker/question must be nonblank strings.")
                    candidate[key] = body[key]
            if candidate.get("state") not in {"in-progress", "complete", "blocked", "awaiting-user"}:
                raise ValueError("QA state is unsupported.")
            if candidate["state"] == "blocked" and not _nonblank(candidate.get("blocker")):
                raise ValueError("Blocked state requires a concrete blocker.")
            if candidate["state"] == "awaiting-user" and not _nonblank(candidate.get("question")):
                raise ValueError("Awaiting-user state requires a question.")
            message = "QA saved in the current native ledger via workflow-ledger qa."
            assertion_issue = workflow._invalidate_assertions(candidate, candidate["working_root"])
            if assertion_issue:
                message = workflow._assertion_feedback(assertion_issue)
            elif candidate["state"] == "complete":
                issue = workflow._validate(candidate, sid, tid, candidate["working_root"])
                if issue:
                    candidate["state"] = "in-progress"
                    if str(issue).startswith("File assertion failed:"):
                        message = workflow._assertion_feedback(issue)
                    else:
                        message = "QA saved; completion withheld: " + str(issue)[:60] + ". Use workflow-ledger qa with fresh actual evidence after fixing work/retesting, or state blocked with blocker / awaiting-user with question. Never flip a verdict without new evidence."
        if inferred_kind: _backup_legacy(path)
        _atomic_write(path, candidate)
        original = workflow.STATE
        try:
            workflow.STATE = state
            if not p.get("agent_id"): workflow._register_active(sid, tid, path)
        finally:
            workflow.STATE = original
    return message


def _protected_scope(p, state):
    ok, actual = _root(p)
    if not ok: return False, actual, None
    _, ledger = _load_existing(p, state)
    if ledger is None: return True, actual, workflow._selected_working_root(p)
    valid, project = workflow._valid_cwd(ledger.get("working_root"))
    if not valid or not _inside(Path(actual), Path(project)):
        return False, "תיקיית העבודה אינה בתוך הפרויקט המקורי ביומן; לא ניתן להרחיב הרשאה אוטומטית.", None
    return True, actual, project


def _pre(p: dict[str, Any], state: Path) -> dict[str, Any]:
    event, tool = _event(p), _tool_name(p)
    data = _input(p)
    if event != "PreToolUse":
        return {}
    if tool in DELEGATION_TOOLS:
        return delegation_gate.check(sys.modules[__name__], p, state)
    if tool == "Bash":
        command = data.get("command")
        parsed = _parse_ledger_command(command)
        if parsed and parsed[0] == "error": return _deny(event, parsed[1])
        ledger_command = parsed[0] if parsed else None
        if ledger_command in {"repair-legacy", "replace-carried-plan"}:
            ok, actual, root = _protected_scope(p, state)
            if not ok: return _deny(event, actual)
            try:
                operation = _repair_previous_legacy if ledger_command == "repair-legacy" else _replace_carried_plan
                return _deny(event, operation(p, state, root, parsed[1]))
            except Exception as exc:
                return _deny(event, "Maintenance refused: " + (str(exc)[:230] if isinstance(exc, ValueError) else type(exc).__name__ + "; no shell command executed."))
        if ledger_command in {"plan", "qa"}:
            ok, actual, root = _protected_scope(p, state)
            if not ok: return _deny(event, actual)
            try:
                return _deny(event, _apply_api(p, state, root, ledger_command, parsed[1]))
            except Exception as exc:
                return _deny(event, f"Ledger {ledger_command} was not accepted: {type(exc).__name__}. " + (str(exc)[:180] if isinstance(exc, ValueError) else "No ledger command was executed."))
        if ledger_command == "continue":
            if p.get("agent_id"):
                return _deny(event, "Native agent continuation cannot select another task through the shared index. Prepare an explicit plan; no prior record changed.")
            ok, actual, root = _protected_scope(p, state)
            if not ok:
                return _deny(event, actual)
            sid, tid = _ids(p)
            if not sid or not tid:
                return _deny(event, "מזהה סשן או תור מקורי חסר; לא ניתן להמשיך יומן קודם.")
            original = workflow.STATE
            try:
                workflow.STATE = state
                _migrate_current(p, state, root)
                path, carried = workflow.continue_task({"session_id": sid, "turn_id": tid, "cwd": root})
            except ValueError as exc:
                return _deny(event, "Continuation refused: " + str(exc)[:180])
            finally:
                workflow.STATE = original
            if carried:
                record = workflow._read(path)
                message = f"Continued {path}; carried_from={record.get('carried_from', '')}; provenance unknown; QA pending: workflow-ledger qa '<JSON>'."
            else:
                record = workflow._read(path)
                message = "Current turn already has a plan. Continue work/checks, then workflow-ledger qa '<JSON>': complete with qa/stages {evidence,verdict,reviewer_id}; or blocked with blocker / awaiting-user with question. No PASS without fresh actual evidence." if _has_acceptance_plan(record) else _prepare_message(path)
            if len(message) > 300:
                raise ValueError("continuation reference exceeds 300 characters; no truncated path emitted")
            return _deny(event, message)
        if ledger_command == "start":
            ok, actual, root = _protected_scope(p, state)
            if not ok:
                return _deny(event, actual)
            try:
                _migrate_current(p, state, root)
            except ValueError as exc:
                return _deny(event, "Task declaration refused: " + str(exc)[:180])
            path, ledger = _ensure_ledger(p, state, root, "substantial")
            if path is None:
                return _deny(event, "מזהה סשן או תור מקורי חסר; לא ניתן ליצור יומן למשימה משמעותית.")
            if ledger is None:
                return _deny(event, "יומן המשימה פגום או אינו תואם למזהים המקוריים; יש לתקן אותו לפני המשך העבודה.")
            message = "Current task already has a frozen plan. Continue work/checks; use workflow-ledger qa '<JSON>' for evidence/verdict or an honest blocked/awaiting-user state." if workflow._plan_ready(ledger) else f"Prepare stages in {path}: DoD, workers, outputs, qa.check, qa.expected; independent QA required."
            if len(message) > 300:
                raise ValueError("substantial ledger reference exceeds 300 characters; no truncated path emitted")
            return _deny(event, message)
        if _readonly_bash(command):
            return {}
        ok, _ = _root(p)
        return {} if ok else _deny(event, "לפני פקודה שעשויה לשנות קבצים, יש לבחור תיקיית פרויקט קיימת ונגישה.")
    if tool not in EDIT_TOOLS:
        return {}
    ok, actual, root = _protected_scope(p, state)
    if not ok:
        return _deny(event, actual)
    paths = _input_paths(tool, data)
    sid, tid = _ids(p)
    if not sid or not tid:
        return _deny(event, "מזהה סשן או תור מקורי חסר; לא ניתן ליצור יומן הכנה לשינוי.")
    denial = _validate_targets(event, paths, root, None, actual)
    if denial:
        return denial
    path, ledger = _ensure_ledger(p, state, root)
    if ledger is None:
        return _deny(event, "יומן המשימה פגום, מקושר או אינו תואם למזהים המקוריים; לא ניתן לאשר שינוי.")
    if not _has_acceptance_plan(ledger):
        return _deny(event, _prepare_message(path))
    return {}


def _failed(p: dict[str, Any]) -> bool:
    if p.get("is_error") is True or p.get("success") is False:
        return True
    if _event(p) == "PostToolUseFailure":
        return True
    response = p.get("tool_response")
    if isinstance(response, dict):
        if response.get("is_error") is True or response.get("isError") is True or response.get("success") is False:
            return True
        if response.get("error"):
            return True
    return False


def _collect_changed(value: Any, depth: int = 0) -> list[str]:
    if depth > 5:
        return []
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"changedFiles", "changed_files"} and isinstance(item, list):
                for entry in item[:MAX_PATHS]:
                    if isinstance(entry, str):
                        found.append(entry)
                    elif isinstance(entry, dict):
                        path = entry.get("file_path") or entry.get("path")
                        if isinstance(path, str):
                            found.append(path)
            elif isinstance(item, dict):
                found.extend(_collect_changed(item, depth + 1))
    return found[:MAX_PATHS]


def _post_paths(tool: str, data: dict[str, Any], payload: dict[str, Any]) -> tuple[list[str], bool]:
    paths: list[str] = []
    uncertain = False
    if tool in EDIT_TOOLS:
        paths = _input_paths(tool, data)
        if tool == "apply_patch" and not paths:
            uncertain = True
    elif tool == "Bash":
        command = data.get("command")
        paths = _collect_changed(payload.get("tool_response")) + _collect_changed(payload.get("tool_result"))
        paths += _collect_changed(payload)
        uncertain = not paths and not _readonly_bash(command)
    return paths[:MAX_PATHS], uncertain


def _state_dir(state: Path) -> Path:
    if state.is_symlink():
        raise OSError("workflow state directory is a symlink")
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not state.is_dir() or state.is_symlink():
        raise OSError("workflow state directory is unsafe")
    try:
        state.chmod(0o700)
    except OSError:
        pass
    return state


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    encoded = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    if len(encoded) > MAX_LEDGER:
        raise ValueError("ledger exceeds size limit")
    if path.is_symlink():
        raise OSError("ledger is a symlink")
    fd, name = tempfile.mkstemp(prefix=".tool-ledger-", dir=str(path.parent))
    temp = Path(name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink():
            raise OSError("ledger became a symlink")
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def _ledger_lock(path: Path):
    """Bound the read/merge/write lock; lock contention reports a fail-open warning."""
    lock_path = path.with_suffix(".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("ledger lock is not a regular file")
        deadline = time.monotonic() + 1.0
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("ledger metadata merge lock timed out")
                time.sleep(0.025)
        yield
    finally:
        if locked:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _record(p: dict[str, Any], paths: list[str], uncertain: bool, state: Path) -> None:
    sid, tid = _ids(p)
    if not sid or not tid:
        return
    ok, actual, root = _protected_scope(p, state)
    if not ok:
        return
    path = state / (hashlib.sha256((sid + "\0" + tid).encode()).hexdigest() + ".json")
    if uncertain and not paths and not path.exists():
        return
    _state_dir(state)
    with _ledger_lock(path):
        return _record_locked(p, paths, uncertain, state, sid, tid, root, actual)


def _record_locked(p, paths, uncertain, state, sid, tid, root, actual):
    original = workflow.STATE
    try:
        workflow.STATE = state
        path = workflow._ledger_path(sid, tid)
        if path.exists():
            ledger = workflow._read(path)
            if ledger.get("session_id") != sid or ledger.get("turn_id") != tid:
                return
            known_root = ledger.get("working_root")
            if known_root and known_root != root:
                return
            if not known_root:
                ledger["working_root"] = root
        else:
            if uncertain and not paths:
                return
            ledger = workflow._new_ledger(sid, tid, root, "small")
            # A tool event can record effects but cannot supply a fabricated plan or QA.
            workflow._create_once(path, ledger)
            # Another tool event may have created the same turn record concurrently.
            ledger = workflow._read(path)
            if ledger.get("session_id") != sid or ledger.get("turn_id") != tid:
                return
        existing = ledger.get("touched_paths", [])
        if not isinstance(existing, list):
            existing = []
        touched = [x for x in existing if isinstance(x, str) and len(x) <= MAX_PATH_CHARS]
        base = Path(actual or root).resolve()
        for raw in paths[:MAX_PATHS]:
            if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_PATH_CHARS:
                continue
            try:
                resolved = str(_resolve_target(raw, base))
            except (OSError, RuntimeError, ValueError):
                continue
            if resolved not in touched and len(touched) < MAX_PATHS:
                touched.append(resolved)
        ledger["touched_paths"] = touched
        warn = uncertain and not ledger.get("tool_uncertainty_warned")
        if uncertain:
            ledger["tool_effect_uncertain"] = True
            ledger["tool_uncertainty_warned"] = True
        _atomic_write(path, ledger)
        return warn
    finally:
        workflow.STATE = original


def _post(p: dict[str, Any], state: Path) -> dict[str, Any]:
    if _event(p) != "PostToolUse" or _failed(p):
        return {}
    tool = _tool_name(p)
    if tool not in EDIT_TOOLS | {"Bash"}:
        return {}
    paths, uncertain = _post_paths(tool, _input(p), p)
    if paths:
        current, ledger = _load_existing(p, state)
        if current is not None and ledger is not None and not current.is_symlink():
            base = Path(workflow._root_hint(p.get("cwd")))
            remaining = []
            for raw in paths:
                try:
                    if _resolve_target(raw, base) == current.resolve():
                        continue
                except (OSError, RuntimeError, ValueError):
                    pass
                remaining.append(raw)
            paths = remaining
    if not paths and not uncertain:
        return {}
    warn = _record(p, paths, uncertain, state)
    if tool == "Bash" and warn:
        return {"systemMessage": "השפעת הפקודה על קבצים אינה ידועה; לא התקבלו נתיבי שינוי מפורשים."}
    return {}


def _baseline_run(payload: dict[str, Any], claude: bool = False) -> dict[str, Any]:
    """Run one hook event. Claude uses its own state namespace and prompt_id turn key."""
    original_state = workflow.STATE
    try:
        normalized = dict(payload)
        normalized["_claude_runtime"] = bool(claude)
        if claude:
            if not normalized.get("turn_id") and isinstance(normalized.get("prompt_id"), str):
                normalized["turn_id"] = normalized["prompt_id"]
            workflow.STATE = CLAUDE_STATE
        event = _event(normalized)
        if event in {"PreToolUse", "PostToolUse", "PostToolUseFailure"}:
            state = CLAUDE_STATE if claude else original_state
            if event == "PreToolUse":
                return _pre(normalized, state)
            return _post(normalized, state)
        # Prompt and Stop hooks share the exact workflow contract, with isolated storage.
        return workflow.run(normalized)
    except Exception as exc:
        if _tool_name(payload) in DELEGATION_TOOLS and _event(payload) == "PreToolUse":
            return _deny("PreToolUse", f"Delegation gate unavailable: {type(exc).__name__}; repair task identity/state before retrying.")
        if _tool_name(payload) == "Bash":
            command = _input(payload).get("command")
            try:
                intercepted = _parse_ledger_command(command) is not None
            except Exception:
                intercepted = isinstance(command, str) and bool(re.match(r"^\s*[\'\"]?workflow-ledger", command))
            if intercepted:
                return _deny("PreToolUse", f"Ledger command intercepted; handler error: {type(exc).__name__}. No shell command executed.")
        if _event(payload) == "PreToolUse" and _tool_name(payload) in EDIT_TOOLS | {"Bash"}:
            return _deny("PreToolUse", f"Hook enforcement failed: {type(exc).__name__}; operation denied.")
        return {"systemMessage": f"Tool scope hook error (fail-open): {type(exc).__name__}: {exc}"}
    finally:
        workflow.STATE = original_state


def run(payload: dict[str, Any], claude: bool = False) -> dict[str, Any]:
    # Hygiene is operator-enabled and leaves existing contracts unchanged otherwise.
    state = CLAUDE_STATE if claude else workflow.STATE
    normalized = dict(payload)
    if claude and not normalized.get("turn_id") and normalized.get("prompt_id"):
        normalized["turn_id"] = normalized["prompt_id"]
    try:
        import hygiene_adapter
        normalized = hygiene_adapter.normalize_shell(sys.modules[__name__], normalized)
        return hygiene_adapter.run(sys.modules[__name__], normalized, state,
                                   lambda: _baseline_run(normalized, claude=claude))
    except Exception as exc:
        if _event(payload) == "Stop":
            return {"decision": "block", "reason": "Hygiene validation unavailable: " + type(exc).__name__}
        if _event(payload) == "PreToolUse":
            return _deny("PreToolUse", "Hygiene validation unavailable: " + type(exc).__name__)
        return {"systemMessage": "Hygiene validation unavailable: " + type(exc).__name__}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--claude", action="store_true")
    args, _ = parser.parse_known_args(argv)
    payload = None
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError("input exceeds limit")
        else:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("input must be an object")
            result = run(payload, claude=args.claude)
    except Exception as exc:
        sys.stderr.write(f"Hook input rejected: {type(exc).__name__}; action not authorized.\n")
        return 2
    if isinstance(payload, dict):
        event, tool = _event(payload), _tool_name(payload)
        if tool in {"exec_command", "shell_command"}:
            tool = "Bash"
        receipt_root = CLAUDE_STATE if args.claude else workflow.STATE.parent
        receipt_state = receipt_root / "hook-receipts" / "tool-scope"
        try:
            import native_receipt
            components = (
                Path(__file__), Path(workflow.__file__), Path(__file__).with_name("hook_receipt.py"),
                Path(native_receipt.__file__), Path(__file__).with_name("hygiene_guard.py"),
                Path(__file__).with_name("hygiene_adapter.py"),
            )
            handler = "tool-scope-claude-v1" if args.claude else "tool-scope-codex-v1"
            version = native_receipt.handler_version(handler, components)
            native_receipt.create_native(receipt_state, payload, native_receipt.outcome_for(result), version)
        except Exception as exc:
            sys.stderr.write(f"Native hook receipt unavailable: {type(exc).__name__}.\n")
            denied = (isinstance(result, dict) and isinstance(result.get("hookSpecificOutput"), dict)
                      and result["hookSpecificOutput"].get("permissionDecision") == "deny")
            if event == "PreToolUse" and not denied:
                result = _deny("PreToolUse", f"Hook receipt unavailable: {type(exc).__name__}; operation denied.")
            elif event == "Stop":
                result = {"decision": "block", "reason": "Hook receipt unavailable; completion not verified."}
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
