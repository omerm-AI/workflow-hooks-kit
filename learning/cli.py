#!/usr/bin/env python3
"""Opt-in local preference and failure learning; stdlib only, never auto-activates."""
from __future__ import annotations
import argparse, contextlib, datetime as dt, fcntl, hashlib, json, os, re, stat, sys, tempfile
from pathlib import Path

MAX_TEXT, MAX_STATE = 500, 256 * 1024
SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}\Z")
SECRET = re.compile(r"(?i)(api[_ -]?key|password|secret|access[_ -]?token)\s*[:=]|\b[A-Za-z0-9_-]{40,}\b")
GENERATED_HEADER = re.compile(r"^## Approved preference ([A-Za-z0-9_-]{1,80})$")
APPROVAL_PREFIX = "Approval: user-confirmed via explicit --approved flag ("
OUTCOMES = {"success", "failure", "blocked"}

class LearningError(ValueError): pass

def clean_text(value, label, limit=MAX_TEXT):
    if not isinstance(value, str): raise LearningError(f"{label} must be text")
    if any(ord(c) < 32 or ord(c) == 127 for c in value): raise LearningError(f"{label} contains control characters")
    value = " ".join(value.split())
    if not value or len(value) > limit:
        raise LearningError(f"{label} must contain 1-{limit} printable characters")
    if SECRET.search(value): raise LearningError(f"{label} looks like it contains a secret")
    return value

def scope_name(value):
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise LearningError("scope must be a lowercase slug (letters, numbers, hyphen, underscore)")
    return value

def today(): return dt.date.today().isoformat()
def empty_state(): return {"version": 1, "preferences": [], "failures": [], "changes": []}

def ensure_real_dir(path):
    path = Path(path).absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try: info = current.lstat()
        except FileNotFoundError:
            try: current.mkdir(mode=0o700)
            except FileExistsError: pass
            info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise LearningError(f"directory path contains a symlink or non-directory: {current}")
    return path

def read_regular(path):
    try: info = path.lstat()
    except FileNotFoundError: return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_STATE:
        raise LearningError(f"file is unsafe, nonregular, or exceeds 256 KB: {path.name}")
    return path.read_bytes()

def atomic_write(path, data):
    ensure_real_dir(path.parent)
    fd, name = tempfile.mkstemp(prefix=".learning-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)

def generated_blocks(data):
    try: lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc: raise LearningError("scoped standard is not valid UTF-8") from exc
    blocks = {}
    for index, line in enumerate(lines):
        match = GENERATED_HEADER.fullmatch(line)
        if not match: continue
        if index + 4 >= len(lines) or lines[index + 1] != "" or lines[index + 3] != "":
            raise LearningError("malformed generated preference block")
        rule, approval = lines[index + 2], lines[index + 4]
        if not approval.startswith(APPROVAL_PREFIX) or not approval.endswith(")"):
            raise LearningError("malformed generated approval note")
        clean_text(rule, "generated rule", 200)
        clean_text(approval[len(APPROVAL_PREFIX):-1], "approval note", 160)
        pid = match.group(1)
        if pid in blocks: raise LearningError("duplicate generated preference block")
        blocks[pid] = rule
    return blocks

def verify_projection(scope, data, preferences, allow_missing=()):
    known = {p["id"]: p for p in preferences if p.get("scope") == scope}
    blocks = generated_blocks(data)
    for pid, rule in blocks.items():
        item = known.get(pid)
        if item is None or item.get("status") != "approved" or item.get("rule") != rule:
            raise LearningError(f"generated preference is not approved for this exact scope and rule: {pid}")
    for pid, item in known.items():
        if item.get("status") == "approved" and blocks.get(pid) != item.get("rule") and pid not in allow_missing:
            raise LearningError(f"approved preference projection is missing or changed: {pid}")
    return blocks

class Store:
    def __init__(self, root):
        requested = Path(root).expanduser().absolute()
        try: requested_info = requested.lstat()
        except FileNotFoundError: requested_info = None
        if requested_info is not None and stat.S_ISLNK(requested_info.st_mode):
            raise LearningError("state directory itself cannot be a symlink")
        requested.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = ensure_real_dir(requested.parent.resolve() / requested.name)
        os.chmod(self.root, 0o700)
        self.file = self.root / "state.json"

    @contextlib.contextmanager
    def lock(self):
        path = self.root / ".learning.lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1: raise LearningError("unsafe lock file")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally: os.close(fd)

    def load(self):
        raw = read_regular(self.file)
        if raw is None: return empty_state()
        try: state = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc: raise LearningError("state file is unreadable or invalid") from exc
        if not isinstance(state, dict) or set(state) != {"version", "preferences", "failures", "changes"} or state["version"] != 1:
            raise LearningError("unsupported state shape")
        if any(not isinstance(state[k], list) for k in ("preferences", "failures", "changes")): raise LearningError("invalid state lists")
        return state

    def save(self, state):
        atomic_write(self.file, self.encoded(state))

    @staticmethod
    def encoded(state):
        data = (json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        if len(data) > MAX_STATE: raise LearningError("state would exceed 256 KB")
        return data

    def standard_path(self, scope): return self.root / "standards" / (scope_name(scope) + ".md")

    def write_standard(self, scope, rule, approval, proposal_id, preferences):
        path = self.standard_path(scope)
        if path.parent.exists() or path.parent.is_symlink(): ensure_real_dir(path.parent)
        prior = read_regular(path)
        existed = prior is not None
        old = prior if existed else b"# Approved local standards: " + scope.encode() + b"\n"
        existing_blocks = verify_projection(scope, old, preferences, allow_missing={proposal_id})
        if proposal_id in existing_blocks: return prior
        digest = hashlib.sha256(old).hexdigest()[:16]
        backup_dir = self.root / "backups" / "standards" / scope_name(scope)
        block = (f"\n## Approved preference {proposal_id}\n\n{rule}\n\n"
                 f"Approval: user-confirmed via explicit --approved flag ({approval})\n").encode()
        combined = old if block in old else old + block
        if len(combined) > MAX_STATE: raise LearningError("scoped standard would exceed 256 KB")
        ensure_real_dir(path.parent)
        ensure_real_dir(backup_dir)
        backup = backup_dir / f"{digest}.bak"
        prior_backup = read_regular(backup)
        if existed and prior_backup is None: atomic_write(backup, old)
        elif prior_backup is not None and prior_backup != old: raise LearningError("backup path already contains different bytes")
        if block in old: return prior
        atomic_write(path, combined)
        return prior

    def restore_standard(self, scope, prior):
        path = self.standard_path(scope)
        if prior is None:
            try: path.unlink()
            except FileNotFoundError: pass
        else: atomic_write(path, prior)

def find_preference(state, pid):
    found = [p for p in state["preferences"] if p["id"] == pid]
    if len(found) != 1: raise LearningError("unknown preference ID")
    return found[0]

def cmd_propose(store, args):
    scope, rule = scope_name(args.scope), clean_text(args.rule, "rule", 200)
    state = store.load(); pid = f"p{len(state['preferences']) + 1:04d}"
    state["preferences"].append({"id": pid, "scope": scope, "rule": rule, "status": "pending", "history": [{"status": "proposed", "date": today()}]})
    store.save(state); print(f"Proposed {pid} for scope {scope}; inactive until approve --approved.")

def cmd_approve(store, args):
    if not args.approved: raise LearningError("approval requires the explicit --approved flag")
    state = store.load(); item = find_preference(state, args.id)
    if item["status"] == "approved": print(f"Already approved: {item['id']}"); return
    approval = clean_text(args.approval, "approval note", 160)
    item["status"] = "approved"; item["history"].append({"status": "approved", "date": today(), "approval_note": approval})
    state["changes"].append({"date": today(), "kind": "standard_added", "scope": item["scope"], "id": item["id"]})
    store.encoded(state)  # Reject size overflow before touching the scoped projection.
    prior = store.write_standard(item["scope"], item["rule"], approval, item["id"], state["preferences"])
    try: store.save(state)
    except BaseException:
        store.restore_standard(item["scope"], prior)
        raise
    print(f"Approved {item['id']} in {item['scope']}; local standard updated with a recoverable backup.")

def cmd_failure(store, args):
    record = {"capability": clean_text(args.capability, "capability"), "task": clean_text(args.task, "task"),
              "model": clean_text(args.model, "model"), "evidence": clean_text(args.evidence, "evidence reference", 160),
              "outcome": args.outcome, "date": today()}
    state = store.load()
    if any(x["evidence"] == record["evidence"] for x in state["failures"]): raise LearningError("evidence reference already recorded; history is preserved")
    state["failures"].append(record); store.save(state); print("Recorded one manually supplied outcome.")

def cmd_report(store, _args):
    state = store.load(); counts = {}
    for row in state["failures"]:
        key = (row["capability"], row["task"], row["model"], row["outcome"]); counts[key] = counts.get(key, 0) + 1
    lines = [f"Local learning report ({len(state['failures'])} outcomes, {len(state['preferences'])} preferences)"]
    for (capability, task, model, outcome), count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:3]:
        lines.append(f"- {capability}/{task}/{model}: {count} {outcome} outcome(s)")
    for change in state["changes"][-3:]:
        if len(lines) >= 4: break
        lines.append(f"- {change['date']}: {change['kind']} in {change['scope']} ({change['id']})")
    if len(lines) == 1: lines.append("- No recorded outcomes or approved changes.")
    print("\n".join(lines))

def cmd_maintain(store, _args):
    state = store.load()
    scopes = {p["scope"] for p in state["preferences"]}
    standards = store.root / "standards"
    if standards.exists() or standards.is_symlink():
        ensure_real_dir(standards)
        files = sorted(standards.glob("*.md"))
        if len(files) > 100: raise LearningError("too many scoped standards to verify")
        for path in files:
            scope = scope_name(path.stem)
            data = read_regular(path)
            if data is not None: verify_projection(scope, data, state["preferences"])
            scopes.add(scope)
    for scope in scopes:
        path = store.standard_path(scope)
        data = read_regular(path)
        approved = any(p.get("scope") == scope and p.get("status") == "approved" for p in state["preferences"])
        if data is None:
            if approved: raise LearningError(f"missing approved scoped standard: {scope}")
        else: verify_projection(scope, data, state["preferences"])
    print(f"Maintenance verified {sum(p['status'] == 'approved' for p in state['preferences'])} approved standard(s); no changes made.")

def cmd_read(store, args):
    path = store.standard_path(args.scope)
    if path.parent.exists() or path.parent.is_symlink(): ensure_real_dir(path.parent)
    data = read_regular(path)
    if data is None: raise LearningError("no approved standard for this scope")
    state = store.load()
    verify_projection(args.scope, data, state["preferences"])
    sys.stdout.write(data.decode("utf-8"))

def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state-dir", default=Path.home() / ".local/share/workflow-hooks-kit/learning", type=Path)
    sub = p.add_subparsers(dest="command", required=True)
    q = sub.add_parser("propose", help="record a manual preference proposal"); q.add_argument("--scope", required=True); q.add_argument("--rule", required=True); q.set_defaults(run=cmd_propose)
    q = sub.add_parser("approve", help="approve and apply one exact pending preference"); q.add_argument("id"); q.add_argument("--approved", action="store_true", help="explicit human confirmation; not authentication"); q.add_argument("--approval", required=True); q.set_defaults(run=cmd_approve)
    q = sub.add_parser("failure", help="record one manually supplied outcome")
    for key in ("capability", "task", "model", "evidence"): q.add_argument("--" + key, required=True)
    q.add_argument("--outcome", choices=sorted(OUTCOMES), required=True); q.set_defaults(run=cmd_failure)
    q = sub.add_parser("report", help="show a bounded local summary"); q.set_defaults(run=cmd_report)
    q = sub.add_parser("maintain", help="verify approved local standards without modifying them"); q.set_defaults(run=cmd_maintain)
    q = sub.add_parser("read", help="print one local approved standard for on-demand use"); q.add_argument("--scope", required=True); q.set_defaults(run=cmd_read)
    return p

def main(argv=None):
    args = parser().parse_args(argv)
    try:
        store = Store(args.state_dir)
        with store.lock(): args.run(store, args)
    except (LearningError, OSError) as exc: print(f"learning: {exc}", file=sys.stderr); return 2
    return 0

if __name__ == "__main__": raise SystemExit(main())
