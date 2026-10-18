#!/usr/bin/env python3
"""Claude Agent route sidecar. It rewrites task input but never grants permission."""
from __future__ import annotations
import argparse, fcntl, hashlib, hmac, json, os, re, stat, sys, tempfile
from contextlib import contextmanager
from pathlib import Path
import delegation_binding, delegation_gate, delegation_guard, hook_receipt, routing_policy

MAX_INPUT = 1_000_000
_KNOWN = {"description", "prompt", "subagent_type", "model", "effort", "run_in_background", "name", "team_name", "mode", "isolation"}
_EFFORTS = {"low", "medium", "high", "xhigh", "max"}

def _unique(pairs):
    out = {}
    for k, v in pairs:
        if k in out: raise ValueError("duplicate JSON key")
        out[k] = v
    return out

def _json(v): return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")

def _policy(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077 or st.st_size > routing_policy.MAX_POLICY_BYTES:
            raise ValueError("unsafe/oversized policy")
        raw = os.read(fd, routing_policy.MAX_POLICY_BYTES + 1)
    finally: os.close(fd)
    obj = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_unique)
    checked, canonical = routing_policy.validate_policy(obj)
    return checked, canonical

def _state(path):
    p = Path(path).expanduser(); st = p.lstat()
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError("unsafe state directory")
    return p

@contextmanager
def _state_lock(state):
    fd=os.open(state/".routing.lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
    locked=False
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077 or st.st_size!=0: raise ValueError("unsafe routing lock")
        fcntl.flock(fd,fcntl.LOCK_EX); locked=True
        yield
    finally:
        if locked: fcntl.flock(fd,fcntl.LOCK_UN)
        os.close(fd)

def _key(state):
    p = state / ".routing-key"
    try: fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        key = os.urandom(32); fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f: f.write(key); f.flush(); os.fsync(f.fileno())
        return key
    try:
        st = os.fstat(fd); key = os.read(fd, 33)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077 or len(key) != 32: raise ValueError("unsafe state key")
        return key
    finally: os.close(fd)

def _write(state, name, value):
    data = dict(value); data["signature"] = hmac.new(_key(state), _json(value), hashlib.sha256).hexdigest(); raw = _json(data)
    if len(raw) > 65536: raise ValueError("state exceeds limit")
    target = state / name
    if target.is_symlink(): raise ValueError("state path symlink")
    fd, tmp = tempfile.mkstemp(prefix=".routing-", dir=str(state))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f: f.write(raw); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, target)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass

def _read(state, name):
    fd = os.open(state / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try: st = os.fstat(fd); raw = os.read(fd, 65537)
    finally: os.close(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077 or len(raw) > 65536: raise ValueError("unsafe state file")
    data = json.loads(raw.decode("ascii"), object_pairs_hook=_unique); sig = data.pop("signature", None)
    expected = hmac.new(_key(state), _json(data), hashlib.sha256).hexdigest()
    if not isinstance(sig, str) or not hmac.compare_digest(sig, expected): raise ValueError("state signature mismatch")
    return data

def _ids(p):
    sid, pid, tid = p.get("session_id"), p.get("prompt_id"), p.get("turn_id")
    for x in (sid, pid, tid):
        if x is not None and (not isinstance(x, str) or not x.strip() or len(x) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in x)): raise ValueError("invalid native identity")
    if pid and tid and pid != tid: raise ValueError("conflicting prompt/turn IDs")
    turn = pid or tid
    if not sid or not turn: raise ValueError("native session and prompt IDs required")
    return sid, turn, bool(pid)

def _context_name(session): return "context-" + hashlib.sha256(session.encode()).hexdigest() + ".json"
def _pending_name(session): return "pending-" + hashlib.sha256(session.encode()).hexdigest() + ".json"

def _stamp(policy, core_dir=None):
    base = Path(__file__).resolve().parent; names = ("routing_guard.py", "routing_policy.py", "delegation_binding.py", "delegation_guard.py", "delegation_gate.py", "hook_receipt.py", "tool_scope_hook.py", "session_workflow_hook.py")
    core = Path(core_dir).expanduser() if core_dir else base
    h = hashlib.sha256()
    for name in names:
        p = core / name if name in {"tool_scope_hook.py", "session_workflow_hook.py"} else base / name
        if p.is_symlink() or not p.is_file(): raise ValueError("runtime component missing")
        raw = p.read_bytes(); h.update(name.encode()); h.update(len(raw).to_bytes(8,"big")); h.update(raw)
    h.update(b"policy\0" + policy); return h.hexdigest()

def _receipt(state, p, outcome, version):
    sid, tid, is_prompt = _ids(p); event = p.get("hook_event_name", p.get("event"))
    marker, _ = hook_receipt.create(state, {"event": event, "session_id": sid, ("prompt_id" if is_prompt else "turn_id"): tid}, outcome, version)
    return marker

def _deny(message): return {"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":str(message)[:300]}}

def _ups(p, state, policy_raw, override):
    if p.get("agent_id"):
        return {"systemMessage":"Child-agent prompt ignored; parent routing context remains unchanged."}
    sid, tid, is_prompt = _ids(p); cwd = p.get("cwd")
    if not isinstance(cwd,str) or not cwd.startswith("/") or len(cwd)>4096: raise ValueError("invalid UPS cwd")
    text = p.get("user_prompt", p.get("prompt", ""))
    if not isinstance(text,str) or len(text)>MAX_INPUT: raise ValueError("invalid UPS text")
    first = text.splitlines()[0] if text else ""; m = re.fullmatch(r"WORKFLOW_MODEL=([!-~]{1,256})", first)
    chosen = override if override is not None else (m.group(1) if m else None)
    try: previous=_read(state,_context_name(sid))
    except FileNotFoundError: previous=None
    if previous is not None and previous.get("turn")==tid:
        if previous.get("cwd")!=cwd or previous.get("policy_hash")!=hashlib.sha256(policy_raw).hexdigest(): raise ValueError("same-prompt UPS context cannot be reset")
        chosen=previous.get("override"); seen=previous.get("seen_tool_ids",[])
    else:
        seen=[]
        try: old_pending=_read(state,_pending_name(sid))
        except FileNotFoundError: old_pending=None
        if old_pending is not None and old_pending.get("consumed") is not True:
            old_pending["superseded"]=True
            _write(state,_pending_name(sid),old_pending)
    _write(state,_context_name(sid),{"session":sid,"turn":tid,"cwd":cwd,"policy_hash":hashlib.sha256(policy_raw).hexdigest(),"override":chosen,"prompt_event":is_prompt,"seen_tool_ids":seen})
    return {"systemMessage":"Routing context recorded without retaining prompt text."}

def _ledger(core,p,state):
    path, data = core._load_existing(p,state)
    if path is None or data is None or data.get("task_kind")!="substantial" or data.get("state")!="in-progress" or type(data.get("schema_version")) is not int or data["schema_version"]!=1: raise ValueError("active substantial ledger required")
    body=core._prepared_plan_body(data)
    if type(body) is not dict or type(body.get("stages")) is not list or not body["stages"]: raise ValueError("prepared stages required")
    return data,body

def _pre(p,core,state,policy,policy_raw,runtime_stamp):
    sid,tid,_=_ids(p); ctx=_read(state,_context_name(sid))
    if p.get("agent_id"):
        raise ValueError("nested child-agent delegation is unsupported")
    if (ctx.get("session"),ctx.get("turn"),ctx.get("cwd"),ctx.get("policy_hash")) != (sid,tid,p.get("cwd"),hashlib.sha256(policy_raw).hexdigest()): raise ValueError("missing/mismatched UPS context")
    data=p.get("tool_input")
    if type(data) is not dict or not {"description","prompt"}<=set(data) or set(data)-_KNOWN: raise ValueError("unsupported Agent input fields")
    if not isinstance(data["prompt"],str) or len(data["prompt"].encode("utf-8","strict"))>32768: raise ValueError("invalid prompt")
    tool=p.get("tool_use_id")
    if not isinstance(tool,str) or not tool.strip() or len(tool)>256: raise ValueError("tool_use_id required")
    seen=ctx.get("seen_tool_ids")
    if type(seen) is not list or len(seen)>128: raise ValueError("invalid route replay history")
    if tool in seen: raise ValueError("tool_use_id replay denied")
    if len(seen)>=128: raise ValueError("per-prompt route history is full")
    for k in ("subagent_type","model","effort","name","team_name","mode","isolation"):
        if k in data and not isinstance(data[k],str): raise ValueError("invalid Agent string field")
    if data.get("subagent_type","general-purpose")!="general-purpose" or data.get("isolation") not in (None,"none","worktree") or data.get("mode") in {"bypassPermissions","dontAsk"}: raise ValueError("unsupported worker configuration")
    if "run_in_background" in data and type(data["run_in_background"]) is not bool: raise ValueError("invalid background flag")
    if data.get("model")=="inherit": raise ValueError("fork/inherited models unsupported")
    if delegation_gate.check(core,p,core.CLAUDE_STATE): raise ValueError("legacy prerequisite denied")
    _,body=_ledger(core,p,core.CLAUDE_STATE); stages=body["stages"]; desc=data["description"]
    m=re.fullmatch(r"\[workflow-stage:([1-9][0-9]*)\] (.+)",desc) if isinstance(desc,str) else None
    num=int(m.group(1)) if m else (1 if len(stages)==1 else 0)
    if not num or num>len(stages): raise ValueError("stage selector required")
    src=stages[num-1]
    if src.get("number")!=num or (m and desc!=f"[workflow-stage:{num}] {src.get('name')}"): raise ValueError("stage selector mismatch")
    override=ctx.get("override")
    stage,route=routing_policy.select_route(src,policy,override); stage["worker_model"]=route["selected_alias"]
    frozen=delegation_binding._frozen_stage(stage,num); effort=frozen["worker_effort"]
    if effort not in _EFFORTS or data.get("effort",effort)!=effort: raise ValueError("native effort conflicts with stage")
    rewritten=dict(data); rewritten.update({"description":f"[workflow-stage:{num}] {src['name']}","prompt":delegation_binding.build_prompt(frozen),"model":route["selected_alias"],"effort":effort,"subagent_type":"general-purpose"}); rewritten.setdefault("run_in_background",False)
    pending={"session":sid,"turn":tid,"tool_use":tool,"policy_hash":route["policy_hash"],"runtime_stamp":runtime_stamp,"stage_hash":hashlib.sha256(_json(frozen)).hexdigest(),"prompt_hash":hashlib.sha256(rewritten["prompt"].encode()).hexdigest(),"expected_model":route["expected_native_model"],"route":dict(route)}
    try: active=_read(state,_pending_name(sid))
    except FileNotFoundError: active=None
    if active is not None and ((active.get("consumed") is not True and not active.get("superseded")) or active.get("tool_use")==tool):
        raise ValueError("another Agent route is still pending for this session")
    ctx["seen_tool_ids"]=seen+[tool]
    _write(state,_context_name(sid),ctx)
    _write(state,_pending_name(sid),pending)
    return {"hookSpecificOutput":{"hookEventName":"PreToolUse","updatedInput":rewritten},"systemMessage":"Frozen route packet prepared; native approval and semantic QA remain required."}

def _post(p,state,policy_raw,runtime_stamp):
    sid,tid,_=_ids(p); inp=p.get("tool_input"); resp=p.get("tool_response"); tool=p.get("tool_use_id")
    if type(inp) is not dict or type(resp) is not dict or not isinstance(tool,str): raise ValueError("invalid post metadata")
    pending=_read(state,_pending_name(sid)); prompt=inp.get("prompt")
    if pending.get("superseded") is True: raise ValueError("pending route superseded by a newer native prompt")
    if pending.get("consumed") is True: raise ValueError("pending route already consumed")
    if pending.get("policy_hash")!=hashlib.sha256(policy_raw).hexdigest() or pending.get("runtime_stamp")!=runtime_stamp:
        raise ValueError("policy or runtime changed after dispatch")
    if (pending.get("session"),pending.get("turn"),pending.get("tool_use"),pending.get("prompt_hash"))!=(sid,tid,tool,hashlib.sha256(prompt.encode()).hexdigest() if isinstance(prompt,str) else None): raise ValueError("post identity/prompt mismatch")
    resolved=resp.get("resolvedModel"); status=resp.get("status"); agent=resp.get("agentId")
    if status not in {"completed","async_launched"} or not isinstance(agent,str) or not agent.strip(): raise ValueError("invalid Agent response")
    ok=resolved==pending.get("expected_model"); observation={"status":status,"agent_hash":hashlib.sha256(agent.encode()).hexdigest(),"resolved_model":resolved,"model_match":ok,"binding_hash":hashlib.sha256(_json(pending)).hexdigest()}
    ver=runtime_stamp+":"+hashlib.sha256(_json(observation)+policy_raw).hexdigest(); marker=_receipt(state,p,"success" if ok else "failure",ver); observation["receipt"]=marker
    pending["consumed"]=True; _write(state,_pending_name(sid),pending)
    _write(state,"result-"+hashlib.sha256(sid.encode()).hexdigest()+".json",observation)
    return {"systemMessage":("Resolved route observed; semantic QA remains required. " if ok else "Resolved model mismatch; do not accept completion. ")+marker}

def run(payload,core_dir=None,policy_path=None,state_dir=None,*,core=None,override_alias=None):
    if type(payload) is not dict:return {}
    event=payload.get("hook_event_name",payload.get("event")); tool=str(payload.get("tool_name") or payload.get("name") or "").rsplit(".",1)[-1]
    if event not in {"UserPromptSubmit","PreToolUse","PostToolUse"} or (event!="UserPromptSubmit" and tool!="Agent"):return {}
    state=None; version="routing-guard-unavailable-v1"
    try:
        state=_state(state_dir)
        with _state_lock(state):
            policy,raw=_policy(policy_path); version=_stamp(raw,core_dir)
            if event=="UserPromptSubmit":return _ups(payload,state,raw,override_alias)
            _ids(payload)
            if event in {"PreToolUse","PostToolUse"}:
                payload=dict(payload)
                if payload.get("prompt_id") and payload.get("turn_id") not in (None,"",payload.get("prompt_id")):
                    raise ValueError("conflicting prompt_id and turn_id")
                if payload.get("prompt_id") and not payload.get("turn_id"):
                    payload["turn_id"]=payload["prompt_id"]
                payload["_claude_runtime"]=True
            if event=="PostToolUse":return _post(payload,state,raw,version)
            try:
                if core is None: core=delegation_guard._load_core(Path(core_dir).expanduser())
                return _pre(payload,core,state,policy,raw,version)
            except Exception as exc:
                marker=_receipt(state,payload,"failure",version)
                return _deny(f"[wf:{marker}] Routing denied: {type(exc).__name__}; {str(exc)[:150]}")
    except Exception as exc:
        if event=="PostToolUse" and state is not None:
            try:
                _ids(payload); marker=_receipt(state,payload,"failure",version)
                return {"systemMessage":f"Agent routing observation failed: {type(exc).__name__}. [wf:{marker}]"}
            except Exception: pass
        if event=="PreToolUse" and state is not None:
            try:
                _ids(payload); marker=_receipt(state,payload,"failure",version); return _deny(f"[wf:{marker}] Routing unavailable: {type(exc).__name__}")
            except Exception: pass
        return _deny(f"Routing unavailable: {type(exc).__name__}") if event=="PreToolUse" else {"systemMessage":"Routing context unavailable."}

def main(argv=None):
    ap=argparse.ArgumentParser(add_help=False); ap.add_argument("--core-dir"); ap.add_argument("--policy"); ap.add_argument("--state-dir"); args,_=ap.parse_known_args(argv)
    try:
        raw=sys.stdin.buffer.read(MAX_INPUT+1)
        if len(raw)>MAX_INPUT: raise ValueError("oversized")
        payload=json.loads(raw.decode("utf-8","strict"),object_pairs_hook=_unique)
    except Exception:
        print(json.dumps(_deny("Malformed or oversized routing hook input; denied."),ensure_ascii=True)); return 0
    print(json.dumps(run(payload,args.core_dir,args.policy,args.state_dir),ensure_ascii=True)); return 0

if __name__=="__main__": raise SystemExit(main())
