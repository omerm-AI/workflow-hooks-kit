#!/usr/bin/env python3
"""Fail-open, bounded workflow observer for native Codex prompt and Stop events."""
from __future__ import annotations
import hashlib
import copy
from contextlib import contextmanager
import fcntl
import json
import os
import re
import sys
import stat
import time
import tempfile
from pathlib import Path
from typing import Any

STATE = Path.home() / ".codex" / "workflow-hooks-kit" / "state"
MAX_INPUT, MAX_LEDGER, MAX_STAGES = 1_000_000, 256_000, 20
MAX_ACTIVE_INDEX = 1024
MAX_ASSERTIONS, MAX_ASSERTION_BYTES = 8, 16_384

# Classifiers are intentionally narrow: ambiguous requests remain conversation/unknown.
FILE_ACTION = re.compile(r"(?:write|edit|create|delete)\s+(?:a\s+|the\s+)?file\b|(?:צור\s+קובץ|עדכן\s+את\s+הקובץ|תקן\s+שגיאת\s+כתיב\s+בקובץ|מחק\s+קובץ)", re.I)
FILE_TARGET = re.compile(r"(?:\bfile\s+[^\s,.;:!?]+|קובץ\s+[^\s,.;:!?]+|הקובץ\s+[^\s,.;:!?]+)", re.I)
IMPLEMENT = re.compile(r"\b(build|implement)\s+(?:a\s+)?(?:system|project|application|app|platform)\b|(?:בנה|תבנה|פתח|תפתח)\s+(?:לי\s+)?(?:מערכת|אפליקציה|פרויקט)", re.I)
RESEARCH = re.compile(r"\b(research|analy[sz]e)\b.{0,80}\b(compare|alternatives|options)\b|חקור\s+והשווה\s+חלופות|מחקר.{0,50}(?:עמוק|משפטי|חלופות)|תחקור\s+ותשווה.{0,80}חלופות|תנתח.{0,80}ותמליץ", re.I)
EXTERNAL = re.compile(r"\b(send|publish|post)\s+(?:a\s+)?(?:message|email|post)\b|שלח\s+הודעה", re.I)
SMALL = re.compile(r"\b(fix|correct|edit|change|write|create|delete)\b|תקן|עדכן|צור|מחק|תרגם|סכם|נסח", re.I)
TEXT_TRANSFORM = re.compile(r"^(?:translate|summari[sz]e|rewrite|rephrase|proofread|format|draft|ת?תרגם|ת?סכם|תסכם|ת?נסח|ת?שכתב|הגהה)(?=\s|:|$)", re.I)


def classify_task(payload: dict[str, Any]) -> str:
    """Return conversation, small, substantial, file, or unknown; never persist input text."""
    text = payload.get("prompt")
    if not isinstance(text, str) or not text.strip():
        return "unknown"
    s = text.strip()
    if FILE_ACTION.search(s):
        return "file"
    if IMPLEMENT.search(s) or RESEARCH.search(s) or EXTERNAL.search(s):
        return "substantial"
    if TEXT_TRANSFORM.match(s):
        return "conversation"
    # Exact time/date questions and ordinary greetings/questions are conversational.
    if len(s) <= 240 and (re.search(r"^(hi|hello|hey|thanks|thank you|מה נשמע|שלום|היי|תודה|מה השעה|מה התאריך)(?:\b|$)", s, re.I)
                          or re.search(r"\b(what time is it|what is the date|what day is it)\??$", s, re.I)):
        return "conversation"
    if len(s) <= 240 and SMALL.search(s):
        return "small"
    if len(s) <= 240 and (s.endswith("?") or s.endswith("؟")):
        return "conversation"
    return "unknown"


def _event(p): return str(p.get("hook_event_name") or p.get("event") or "")
def _message(text, decision=None):
    if len(text) > 300: text = text[:297] + "..."
    r = {"systemMessage": text}
    if decision:
        r.update(decision=decision)
        if decision == "block": r["reason"] = text
    return r


def _valid_cwd(raw):
    if not isinstance(raw, str) or not raw: return False, "נתיב העבודה חסר. יש לבחור תיקיית פרויקט קיימת ומוגדרת."
    p = Path(raw)
    if not p.is_absolute(): return False, "נתיב העבודה אינו מוחלט. יש לבחור תיקיית פרויקט קיימת ומוגדרת."
    try: resolved, home = p.resolve(strict=True), Path.home().resolve()
    except (OSError, RuntimeError): return False, "תיקיית העבודה אינה קיימת או אינה נגישה. יש לבחור תיקיית פרויקט קיימת."
    if not resolved.is_dir(): return False, "נתיב העבודה אינו תיקייה."
    if resolved in {Path("/"), home, home.parent} or resolved == Path("/tmp") or Path("/tmp") in resolved.parents or Path("/private/tmp") in resolved.parents:
        return False, "תיקיית העבודה כללית או זמנית. יש לבחור תיקיית פרויקט מוגדרת."
    if not os.access(resolved, os.R_OK | os.X_OK): return False, "אין גישה לתיקיית העבודה."
    return True, str(resolved)


def _root_hint(raw):
    try:
        p = Path(raw).resolve(strict=True)
        return str(p) if p.is_dir() else str(raw or "")
    except (OSError, RuntimeError, TypeError): return str(raw or "")


def _selected_working_root(payload):
    actual = _root_hint(payload.get("cwd"))
    if payload.get("_claude_runtime") is True:
        try:
            valid, project = _valid_cwd(os.environ.get("CLAUDE_PROJECT_DIR"))
            if valid and (Path(actual) == Path(project) or Path(project) in Path(actual).parents):
                return project
        except (OSError, RuntimeError, ValueError): pass
    return actual


def _state_dir(create=False):
    if STATE.is_symlink(): raise RuntimeError("state directory is a symlink")
    if create: STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not STATE.is_dir(): raise RuntimeError("state directory is unavailable")
    if create:
        try: STATE.chmod(0o700)
        except OSError: pass
    return STATE


def _ledger_path(session_id, turn_id, create=False):
    digest = hashlib.sha256((session_id + "\0" + turn_id).encode()).hexdigest()
    return _state_dir(create) / (digest + ".json")


@contextmanager
def _file_lock(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("workflow lock is not a regular file")
        deadline = time.monotonic() + 1.0
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("workflow lock timed out")
                time.sleep(0.025)
        yield
    finally:
        if locked:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _active_index_path(sid):
    return _state_dir() / (hashlib.sha256(sid.encode()).hexdigest() + ".active.json")


def _read_active(sid):
    path = _active_index_path(sid)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ACTIVE_INDEX:
                return None
            raw = stream.read(MAX_ACTIVE_INDEX + 1)
        if len(raw) > MAX_ACTIVE_INDEX:
            return None
        index = json.loads(raw.decode("utf-8"))
        if not isinstance(index, dict) or index.get("schema_version") != 1 or index.get("session_id") != sid:
            return None
        if not isinstance(index.get("turn_id"), str) or not index["turn_id"].strip():
            return None
        if not isinstance(index.get("working_root"), str) or not Path(index["working_root"]).is_absolute():
            return None
        return index
    except (OSError, ValueError, UnicodeError):
        return None


def _write_private(path, data, limit):
    encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
    if len(encoded) > limit:
        raise ValueError("workflow metadata exceeds bounded size")
    if path.is_symlink():
        raise ValueError("workflow metadata path is a symlink")
    fd, name = tempfile.mkstemp(prefix=".workflow-", dir=str(path.parent))
    temp = Path(name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink():
            raise ValueError("workflow metadata became a symlink")
        os.replace(temp, path)
    finally:
        try: temp.unlink()
        except FileNotFoundError: pass


def _plan_ready(ledger):
    if not isinstance(ledger, dict): return False
    if ledger.get("task_kind") == "small":
        stages = [ledger] if any(key in ledger for key in ("definition_of_done", "outputs", "qa")) else ledger.get("stages")
        if not isinstance(stages, list) or len(stages) != 1: return False
    elif ledger.get("task_kind") == "substantial":
        stages = ledger.get("stages")
        if not isinstance(stages, list) or not stages or len(stages) > MAX_STAGES: return False
    else: return False
    for stage in stages:
        if not isinstance(stage, dict): return False
        done, qa = stage.get("definition_of_done"), stage.get("qa")
        if not isinstance(done, str) or not done.strip() or not _valid_outputs(stage.get("outputs")): return False
        if not isinstance(qa, dict) or any(not isinstance(qa.get(key), str) or not qa[key].strip() for key in ("check", "expected")): return False
    return True


def _register_active(sid, tid, ledger_path):
    """Register material starts only; a blank new turn cannot hide a prepared prior plan."""
    try:
        ledger = _read(ledger_path)
        if ledger.get("session_id") != sid or ledger.get("turn_id") != tid: return False
        if ledger.get("source_agent_id"): return False
        root = ledger.get("working_root")
        ok, resolved = _valid_cwd(root)
        if not ok: return False
        index_path = _active_index_path(sid)
        with _file_lock(index_path.with_suffix(".lock")):
            old = _read_active(sid)
            if old and old["turn_id"] != tid and not _plan_ready(ledger):
                try:
                    previous = _read(_ledger_path(sid, old["turn_id"]))
                    if (previous.get("session_id") == sid and previous.get("turn_id") == old["turn_id"]
                            and previous.get("state") not in {"complete", "blocked"}
                            and _root_hint(previous.get("working_root")) == resolved
                            and old["working_root"] == resolved and _plan_ready(previous)):
                        return True
                except (OSError, ValueError): pass
            index = {"schema_version": 1, "session_id": sid, "turn_id": tid, "working_root": resolved}
            _write_private(index_path, index, MAX_ACTIVE_INDEX)
        return True
    except (OSError, ValueError):
        # An unusable optional continuity index never expands scope or changes task QA.
        return False


def continue_task(payload):
    """Explicitly carry one same-session, same-project incomplete plan into a native turn."""
    if payload.get("agent_id"):
        raise ValueError("Native agent continuation cannot select another task through the shared index.")
    sid, tid = payload.get("session_id"), payload.get("turn_id")
    if not isinstance(sid, str) or not sid.strip() or not isinstance(tid, str) or not tid.strip():
        raise ValueError("native session_id and turn_id are required")
    ok, root = _valid_cwd(payload.get("cwd"))
    if not ok: raise ValueError("continuation requires a valid project root")
    current = _ledger_path(sid, tid, create=True)
    with _file_lock(current.with_suffix(".lock")):
        if current.exists():
            existing = _read(current)
            if existing.get("session_id") != sid or existing.get("turn_id") != tid:
                raise ValueError("current ledger native identifiers do not match")
            if _plan_ready(existing) or existing.get("state") in {"complete", "blocked"}:
                if existing.get("task_kind") in {"small", "substantial"}:
                    start_task(payload, existing["task_kind"])
                return current, False
        index = _read_active(sid)
        source = None
        if index and index["turn_id"] != tid and index["working_root"] == root:
            try:
                source = _read(_ledger_path(sid, index["turn_id"]))
                if (source.get("schema_version") != 1 or source.get("session_id") != sid
                        or source.get("turn_id") != index["turn_id"]
                        or source.get("state") in {"complete", "blocked"}
                        or not isinstance(source.get("working_root"), str)
                        or not Path(source["working_root"]).is_absolute()
                        or _root_hint(source.get("working_root")) != root or not _plan_ready(source)):
                    source = None
            except (OSError, ValueError): source = None
        if isinstance(source, dict) and source.get("source_agent_id"):
            raise ValueError("Active source has native agent provenance; prepare an explicit plan instead of carrying it.")
        if source is None:
            start_task(payload, "small")
            return current, False
        carried = _new_ledger(sid, tid, source["working_root"], source["task_kind"])
        for key in ("definition_of_done", "outputs", "qa", "stages", "attempts", "worker_id", "worker_model", "worker_effort", "model_rationale", "inputs", "boundaries", "dependencies"):
            if key in source: carried[key] = copy.deepcopy(source[key])
        stages = carried.get("stages", [])
        for stage in [carried] + (stages if isinstance(stages, list) else []):
            if isinstance(stage, dict) and isinstance(stage.get("qa"), dict):
                stage["qa"]["verdict"], stage["qa"]["evidence"] = "pending", "pending"
        carried.update(state="in-progress", carried_from=index["turn_id"])
        _write_private(current, carried, MAX_LEDGER)
        start_task(payload, source["task_kind"])
        return current, True


def _known_projectless(session_id, cwd):
    # Portable hosts expose no reliable UI workspace binding.
    return False


def _new_ledger(session_id, turn_id, root, kind):
    return {"schema_version": 1, "task_kind": kind, "session_id": session_id, "turn_id": turn_id,
            "working_root": root, "state": "awaiting-plan", "attachment_verified": False, "stages": []}


def start_task(payload: dict[str, Any], kind: str = "substantial") -> Path:
    """Lazily create a task ledger from native identifiers, without requiring classification.

    Intended for substantive work explicitly declared by the lead. `kind` is `small`
    or `substantial`; request text is never copied into state.
    """
    sid, tid = payload.get("session_id"), payload.get("turn_id")
    if not isinstance(sid, str) or not sid.strip() or not isinstance(tid, str) or not tid.strip():
        raise ValueError("native session_id and turn_id are required")
    if kind not in {"small", "substantial"}:
        raise ValueError("kind must be small or substantial")
    path = _ledger_path(sid, tid, create=True)
    record = _new_ledger(sid, tid, _root_hint(payload.get("cwd")), kind)
    if payload.get("agent_id"): record["source_agent_id"] = str(payload["agent_id"])[:256]
    _create_once(path, record)
    if not payload.get("agent_id"): _register_active(sid, tid, path)
    return path


def _create_once(path, ledger):
    encoded = json.dumps(ledger, ensure_ascii=False, indent=2).encode()
    if len(encoded) > MAX_LEDGER: raise RuntimeError("new ledger exceeds size limit")
    fd, tmp = tempfile.mkstemp(prefix=".ledger-", dir=str(path.parent))
    tp = Path(tmp)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f: f.write(encoded); f.flush(); os.fsync(f.fileno())
        try: os.link(tp, path, follow_symlinks=False)
        except FileExistsError: pass
    finally:
        try: tp.unlink()
        except FileNotFoundError: pass


def _read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_LEDGER: raise ValueError("ledger missing, unsafe, or oversized")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict): raise ValueError("ledger must be an object")
    return data


def retry_action(ladder: list[str], attempts: list[dict], current_model: str) -> str:
    """Decide the next action using only the caller's explicitly available model order."""
    if not isinstance(attempts, list) or any(not isinstance(item, dict) for item in attempts):
        return "blocked"
    last = attempts[-1] if attempts else {}
    if last.get("verdict") == "pass":
        return "done"
    if last.get("verdict") in {"blocked", "external_prerequisite", "external_prereq"} or last.get("external_prerequisite") or last.get("external_prereq"):
        return "blocked"
    if not isinstance(ladder, list) or not ladder or any(not isinstance(model, str) or not model.strip() for model in ladder) or len(set(ladder)) != len(ladder):
        return "blocked"
    if current_model not in ladder:
        return "blocked"
    failures = sum(item.get("verdict") == "fail" and (item.get("worker_model") or item.get("model")) == current_model for item in attempts)
    if failures < 3:
        return "retry"
    return "return_user" if current_model == ladder[-1] else "escalate"


def _attempt_issue(stage):
    if "attempts" not in stage:
        return None
    attempts = stage["attempts"]
    if not isinstance(attempts, list) or any(not isinstance(item, dict) for item in attempts):
        return "רשומת הניסיונות אינה תקינה."
    counts = {}
    for attempt in attempts:
        model = attempt.get("worker_model") or attempt.get("model") or stage.get("worker_model")
        if not isinstance(model, str) or not model.strip():
            return "ברשומת ניסיון חסר מזהה מודל."
        counts[model] = counts.get(model, 0) + 1
        if counts[model] > 3:
            return "לכל מודל מותרים עד שלושה ניסיונות."
    return None


def _valid_outputs(outputs):
    return isinstance(outputs, list) and bool(outputs) and all(isinstance(item, str) and item.strip() for item in outputs)


def _relative_output_key(raw):
    """Lexically normalize relative outputs, never expand an absolute or parent path."""
    if (not isinstance(raw, str) or not raw.strip() or "\0" in raw
            or Path(raw).is_absolute() or ".." in raw.split("/")):
        return None
    key = Path(raw).as_posix()
    return key if key != "." else None


def _assertions_shape(assertions, outputs):
    """Optional literal checks only; no assertions means structural QA, not DoD proof."""
    if not isinstance(assertions, list) or len(assertions) > MAX_ASSERTIONS:
        raise ValueError("QA assertions must be an array of at most eight literal file checks.")
    output_keys = {_relative_output_key(output) for output in outputs} if isinstance(outputs, list) else set()
    for assertion in assertions:
        if not isinstance(assertion, dict) or set(assertion) != {"path", "expected_text"}:
            raise ValueError("Each assertion accepts exactly path and expected_text.")
        path, expected = assertion["path"], assertion["expected_text"]
        if (not isinstance(path, str) or not path.strip() or "\0" in path
                or Path(path).is_absolute() or any(part in {"", ".", ".."} for part in path.split("/"))):
            raise ValueError("Assertion path must name a relative file inside the protected working root.")
        if path not in output_keys:
            raise ValueError("Assertion path must match this small task/stage's declared relative outputs.")
        if not isinstance(expected, str):
            raise ValueError("Assertion expected_text must be a UTF-8 string.")
        try:
            size = len(expected.encode("utf-8"))
        except UnicodeError as exc:
            raise ValueError("Assertion expected_text must be valid UTF-8.") from exc
        if size > MAX_ASSERTION_BYTES:
            raise ValueError("Assertion expected_text exceeds 16KB.")


def _assertion_issue(qa, root, outputs):
    """Read only declared files, using no-follow descriptors and bounded bytes."""
    if "assertions" not in qa:
        return None
    try:
        _assertions_shape(qa["assertions"], outputs)
    except ValueError as exc:
        return str(exc)
    for assertion in qa["assertions"]:
        descriptors = []
        try:
            protected = Path(root)
            if not protected.is_absolute() or protected.resolve(strict=True) != protected:
                raise ValueError("protected root changed or contains a symlink")
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            directory = os.open(str(protected), flags | os.O_DIRECTORY)
            descriptors.append(directory)
            parts = assertion["path"].split("/")
            for part in parts[:-1]:
                directory = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
                descriptors.append(directory)
            fd = os.open(parts[-1], flags, dir_fd=directory)
            descriptors.append(fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("declared target must be a regular file")
            if info.st_size > MAX_ASSERTION_BYTES:
                raise ValueError("declared file exceeds 16KB")
            data = bytearray()
            while len(data) <= MAX_ASSERTION_BYTES:
                chunk = os.read(fd, MAX_ASSERTION_BYTES + 1 - len(data))
                if not chunk: break
                data.extend(chunk)
            if len(data) > MAX_ASSERTION_BYTES:
                raise ValueError("declared file exceeds 16KB")
            if data.decode("utf-8") != assertion["expected_text"]:
                raise ValueError("file text differs from prepared expected_text")
        except (OSError, ValueError, UnicodeError, RuntimeError) as exc:
            return f"File assertion failed: {assertion['path']}: {exc}. Fix the declared file and rerun QA."
        finally:
            for fd in reversed(descriptors): os.close(fd)
    return None


def _invalidate_assertions(ledger, root):
    """A claimed PASS cannot survive a failed declared literal check."""
    stages = [ledger] if ledger.get("task_kind") == "small" and "qa" in ledger else ledger.get("stages", [])
    first = None
    for stage in stages:
        qa = stage.get("qa", {}) if isinstance(stage, dict) else {}
        if isinstance(qa, dict) and qa.get("verdict") == "pass":
            issue = _assertion_issue(qa, root, stage.get("outputs"))
            if issue:
                qa["verdict"] = "fail"
                first = first or issue
    if first: ledger["state"] = "in-progress"
    return first


def _assertion_feedback(issue, warning=""):
    """Bound repair feedback without cutting a declared path into a fake target."""
    guidance = " Fix/retest; workflow-ledger qa '<JSON>' with fresh evidence. Or state blocked with blocker / awaiting-user with question."
    suffix = guidance + (" " + warning if warning else "")
    prefix = "QA failed; completion withheld: "
    detail = str(issue)
    if len(prefix + detail + suffix) > 300:
        detail = "Declared file assertion failed."
    return prefix + detail + suffix


def _validate(d, sid, tid, root):
    if d.get("schema_version") != 1 or d.get("session_id") != sid or d.get("turn_id") != tid or d.get("working_root") != root:
        return "פרטי היומן אינם תואמים לסשן, לתור או לתיקיית העבודה."
    if d.get("state") == "awaiting-user":
        return None if isinstance(d.get("question"), str) and d["question"].strip() else "המתנה למשתמש דורשת שאלה ברורה."
    if d.get("state") == "blocked":
        return None if isinstance(d.get("blocker"), str) and d["blocker"].strip() else "חסם דורש תיאור ברור."
    if d.get("task_kind") == "small":
        if d.get("state") != "complete": return "היומן אינו מציין השלמה או חסם."
        # Compact tasks record completion directly; older one-stage ledgers remain valid.
        if any(k in d for k in ("definition_of_done", "outputs", "qa")):
            stage = d
        else:
            stages = d.get("stages")
            if not isinstance(stages, list) or len(stages) != 1: return "השלמת שינוי קטן דורשת רשומה מתועדת."
            stage = stages[0]
        if isinstance(stage, dict):
            issue = _attempt_issue(stage)
            if issue: return issue
        qa = stage.get("qa", {}) if isinstance(stage, dict) else {}
        if not isinstance(stage, dict) or not isinstance(stage.get("definition_of_done"), str) or not stage["definition_of_done"].strip():
            return "בשינוי קטן חסרה הגדרת הצלחה."
        if not _valid_outputs(stage.get("outputs")): return "בשינוי קטן חסר תוצר תקין."
        if not isinstance(qa, dict) or any(not isinstance(qa.get(k), str) or not qa[k].strip() for k in ("check", "expected", "evidence", "verdict", "reviewer_id")):
            return "בשינוי קטן חסרים פרטי בדיקה."
        if qa["verdict"] != "pass" or qa["evidence"].strip().lower() == "pending":
            return "בדיקת השינוי הקטן לא עברה או טרם בוצעה."
        return _assertion_issue(qa, root, stage.get("outputs"))
    stages = d.get("stages")
    if not isinstance(stages, list): return "מבנה השלבים ביומן אינו תקין."
    if not stages or len(stages) > MAX_STAGES: return "חסרה תוכנית שלבים ממוספרת."
    ids, names = [], set()
    for st in stages:
        if not isinstance(st, dict): return "מבנה שלב אינו תקין."
        issue = _attempt_issue(st)
        if issue: return issue
        n = st.get("number"); ids.append(n)
        if not isinstance(n, int) or isinstance(n, bool) or n < 1: return "לכל שלב נדרש מספר חיובי."
        name = st.get("name")
        if not isinstance(name, str) or not name.strip() or name in names: return "שמות השלבים חייבים להיות ייחודיים."
        names.add(name)
        for k in ("definition_of_done", "worker_id", "worker_model", "worker_effort", "model_rationale"):
            if not isinstance(st.get(k), str) or not st[k].strip(): return f"בשלב {n} חסר שדה: {k}."
        if st["worker_effort"] not in {"low", "medium", "high", "xhigh", "max", "ultra", "minimal", "none"}: return "רמת מאמץ אינה נתמכת."
        if not _valid_outputs(st.get("outputs")): return f"בשלב {n} חסר תוצר."
        if not all(isinstance(st.get(k), list) for k in ("inputs", "boundaries", "dependencies")): return f"בשלב {n} חסרים גבולות, קלטים או תלויות."
        qa = st.get("qa")
        if not isinstance(qa, dict) or any(not isinstance(qa.get(k), str) or not qa[k].strip() for k in ("check", "expected", "evidence", "verdict", "reviewer_id")): return f"בשלב {n} חסרים פרטי QA."
        if qa["reviewer_id"] == st["worker_id"]: return f"בשלב {n} הבודק חייב להיות נפרד מהעובד."
        if qa["verdict"] not in {"pass", "fail", "blocked"}: return "תוצאת QA אינה תקינה."
        if qa["verdict"] == "pass" and qa["evidence"].strip().lower() == "pending": return "נדרשת ראיית QA חדשה לאחר המשך המשימה."
        if qa["verdict"] == "pass":
            issue = _assertion_issue(qa, root, st.get("outputs"))
            if issue: return issue
    if ids != list(range(1, len(stages)+1)): return "מספרי השלבים אינם עוקבים."
    if d.get("state") != "complete": return "היומן אינו מציין השלמה או חסם."
    if any(s["qa"]["verdict"] != "pass" for s in stages): return "בדיקת QA נכשלה או חסומה."
    return None


def _prompt(p):
    if p.get("agent_id") or classify_task(p) != "substantial": return {}
    sid, tid = p.get("session_id"), p.get("turn_id")
    if not isinstance(sid, str) or not sid.strip() or not isinstance(tid, str) or not tid.strip():
        return _message("מזהה סשן או תור חסר; לא ניתן ליצור יומן למשימה משמעותית.")
    path = start_task({**p, "cwd": _selected_working_root(p)}, "substantial")
    ctx = "Substantial task: use workflow-ledger plan '<JSON>' for stages/DoD/workers/outputs/check/expected, then workflow-ledger qa '<JSON>' for evidence/verdict. Labels are declarations; verify actual work."
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}}


def _claim_stop_block(path):
    marker = path.with_suffix(".stop-once")
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        return False
    try:
        os.write(fd, b"1")
        os.fsync(fd)
    finally:
        os.close(fd)
    return True


def _stop(p):
    if p.get("stop_hook_active") is True or p.get("agent_id"): return {}
    sid, tid = p.get("session_id"), p.get("turn_id")
    if not isinstance(sid, str) or not sid.strip() or not isinstance(tid, str) or not tid.strip(): return {}
    try: path = _ledger_path(sid, tid)
    except Exception: return {}
    if not path.exists(): return {}
    drift = False
    assertion_issue = None
    preflight_issue = False
    try:
        with _file_lock(path.with_suffix(".lock")):
            d = _read(path)
            if type(d.get("schema_version")) is not int or d.get("schema_version") != 1 or d.get("session_id") != sid or d.get("turn_id") != tid:
                issue = "Unsupported ledger schema/native identity; no assertions read or record changed."
                preflight_issue = True
            elif not isinstance(d.get("task_kind"), str) or d.get("task_kind") not in {"small", "substantial"}:
                issue = "Legacy task_kind missing; use explicit repair-legacy for its previous native turn. No record changed." if "task_kind" not in d else "Unsupported task_kind; no assertions read or record changed."
                preflight_issue = True
            elif (d.get("task_kind") == "small" and d.get("state") == "awaiting-plan"
                    and not d.get("touched_paths") and not d.get("tool_effect_uncertain")):
                return {}
            else:
                original_root = d.get("working_root")
                if not isinstance(original_root, str) or not Path(original_root).is_absolute():
                    issue = "ביומן חסרה תיקיית העבודה המקורית."
                else:
                    drift = _root_hint(p.get("cwd")) != _root_hint(original_root)
                    assertion_issue = _invalidate_assertions(d, original_root)
                    if assertion_issue: _write_private(path, d, MAX_LEDGER)
                    issue = assertion_issue or _validate(d, sid, tid, original_root)
    except (OSError, ValueError, json.JSONDecodeError):
        issue = "יומן המשימה חסר או פגום."
    warning = "CWD changed; original root retained." if drift else ""
    if issue:
        if preflight_issue:
            decision = "block" if _claim_stop_block(path) else None
            return _message(str(issue) + " Review native schema before retrying. Legacy maintenance: workflow-ledger repair-legacy '<previous-turn-id>'. No PASS claimed.", decision)
        if assertion_issue or str(issue).startswith("File assertion failed:"):
            decision = "block" if _claim_stop_block(path) else None
            return _message(_assertion_feedback(assertion_issue or issue, warning), decision)
        guidance = "Rerun checks; no PASS without fresh evidence. workflow-ledger qa '<JSON>': complete with qa/stages {evidence,verdict,reviewer_id}; small: reviewer_id=lead means you; stages need separate reviewer. Or blocked+blocker / awaiting-user+question."
        if _claim_stop_block(path):
            return _message(str(issue)[:45] + ". " + guidance + (" " + warning if warning else ""), "block")
        return _message("Cap used. " + str(issue)[:35] + ". " + guidance + (" " + warning if warning else ""))

    return _message(warning) if warning else {}


def run(payload):
    try:
        event = _event(payload)
        if event == "UserPromptSubmit": return _prompt(payload)
        if event == "Stop": return _stop(payload)
        return {}
    except Exception as exc:
        return {"systemMessage": f"Session workflow hook error (fail-open): {type(exc).__name__}: {exc}"}


def main():
    data = None
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT+1)
        if len(raw) > MAX_INPUT: result = {"systemMessage": "Session workflow hook input exceeds limit (fail-open)."}
        else:
            data = json.loads(raw.decode("utf-8")); result = run(data) if isinstance(data, dict) else {}
    except Exception as exc: result = {"systemMessage": f"Session workflow hook input error (fail-open): {type(exc).__name__}: {exc}"}
    if isinstance(data, dict):
        try:
            import native_receipt
            components = (Path(__file__), Path(__file__).with_name("hook_receipt.py"),
                          Path(native_receipt.__file__))
            version = native_receipt.handler_version("workflow-codex-v1", components)
            receipt_state = STATE.parent / "hook-receipts" / "session-workflow"
            native_receipt.create_native(receipt_state, data,
                                         native_receipt.outcome_for(result, skipped=not bool(result)),
                                         version)
        except Exception as exc:
            sys.stderr.write(f"Native hook receipt unavailable: {type(exc).__name__}.\n")
    sys.stdout.write(json.dumps(result, ensure_ascii=False)+"\n"); return 0

if __name__ == "__main__": raise SystemExit(main())
