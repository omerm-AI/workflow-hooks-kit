"""Opt-in strict hygiene boundary. Uninspectable shell writes are refused.

This covers native calls delivered to this adapter, not arbitrary OS/MCP writes.
The operator's state policy enables it; model-authored payloads cannot enable or
change the protected project root. Review declarations are not semantic proof.
"""
from __future__ import annotations
import json
import hashlib
import os
from pathlib import Path
import shlex
import stat
import hygiene_guard

# Complete native identities only; connector suffixes are never a capability.
NATIVE_READ_TOOLS = {'Read', 'Glob', 'Grep', 'LS', 'List'}
NATIVE_EDIT_TOOLS = {'Edit', 'Write', 'apply_patch', 'MultiEdit', 'NotebookEdit'}
NATIVE_DELEGATION_TOOLS = {'Agent', 'spawn_agent', 'Task'}
NATIVE_METADATA_TOOLS = {'update_plan', 'request_user_input', 'AskUserQuestion', 'TodoWrite', 'TaskCreate', 'TaskUpdate', 'TaskList', 'TaskGet'}
NATIVE_SHELL_TOOLS = {'Bash', 'exec_command', 'shell_command'}


def native_name(payload):
    raw = payload.get('tool_name') or payload.get('name') or ''
    names = NATIVE_READ_TOOLS | NATIVE_EDIT_TOOLS | NATIVE_DELEGATION_TOOLS | NATIVE_METADATA_TOOLS | NATIVE_SHELL_TOOLS
    if raw in names:
        return raw
    if isinstance(raw, str) and raw.startswith('functions.') and raw[10:] in names:
        return raw[10:]
    return None


def enabled(state: Path) -> bool:
    policy = state / 'hygiene-policy.json'
    if not policy.exists():
        return False
    if policy.is_symlink() or not stat.S_ISREG(policy.stat().st_mode) or policy.stat().st_size > 4096:
        raise ValueError('Unsafe hygiene policy')
    body = json.loads(policy.read_text())
    if body != {'schema': 1, 'mode': 'enforce'}:
        raise ValueError('Unknown hygiene policy; explicit repair required')
    return True


def _command(core, payload):
    command = core._input(payload).get('command')
    if not isinstance(command, str):
        return None
    try:
        args = shlex.split(command)
    except ValueError:
        if command.lstrip().startswith('workflow-hygiene'):
            raise ValueError('Malformed hygiene command')
        return None
    if not args or args[0] != 'workflow-hygiene':
        return None
    if len(args) != 3 or args[1] not in {'review', 'restore', 'inspect', 'read'}:
        raise ValueError("Use exactly workflow-hygiene inspect|read|review|restore '<JSON>'")
    body = json.loads(args[2])
    if not isinstance(body, dict):
        raise ValueError('Review must be an object')
    return args[1], body


def normalize_shell(core, payload):
    tool = native_name(payload)
    if tool in {'exec_command', 'shell_command'}:
        data = dict(core._input(payload))
        if 'command' not in data and isinstance(data.get('cmd'), str):
            data['command'] = data['cmd']
        return {**payload, 'tool_name': 'Bash', 'tool_input': data}
    return payload


def run(core, payload, state, delegate):
    """Delegate baseline gates first, then impose the independent hygiene gate."""
    if not enabled(state):
        return delegate()
    event = core._event(payload)
    if event == 'PreToolUse':
        native = native_name(payload)
        if native is None or (native in NATIVE_DELEGATION_TOOLS and native not in getattr(core, 'DELEGATION_TOOLS', set())):
            return core._deny(event, 'Strict hygiene: unknown tool or connector has no verified write boundary; no tool executed.')
    event, tool = core._event(payload), core._tool_name(payload)
    payload = normalize_shell(core, payload)
    tool = core._tool_name(payload)
    guard_state = state / 'hygiene'
    if event == 'PreToolUse' and tool == 'Bash':
        command_body = _command(core, payload)
        if command_body is not None:
            action, body = command_body
            ok, actual, root = core._protected_scope(payload, state)
            if not ok:
                return core._deny(event, actual)
            if action == 'read':
                if set(body) - {'path', 'offset', 'limit'} or 'path' not in body:
                    raise ValueError('Read requires path and optional offset/limit')
                offset, limit = body.get('offset', 0), body.get('limit', 8000)
                if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 8000:
                    raise ValueError('Read offset/limit invalid')
                protected, _sid, _turn = hygiene_guard._identity({**payload, 'cwd': root})
                rel = hygiene_guard._rel(protected, body['path'])
                inspected = hygiene_guard._file(protected, rel)
                if inspected is None:
                    raise ValueError('Read target absent')
                fd = os.open(str(protected / rel), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, 'rb') as stream:
                    actual = os.fstat(stream.fileno())
                    signature = [actual.st_dev, actual.st_ino, actual.st_size, actual.st_mtime_ns, actual.st_ctime_ns]
                    if not stat.S_ISREG(actual.st_mode) or signature != inspected['signature']:
                        raise ValueError('Read target identity changed')
                    data = stream.read(hygiene_guard.MAX_FILE_BYTES + 1)
                if len(data) > hygiene_guard.MAX_FILE_BYTES or hygiene_guard._file(protected, rel) != inspected:
                    raise ValueError('Read target changed or exceeded bound')
                if hashlib.sha256(data).hexdigest() != inspected['sha256']:
                    raise ValueError('Read target changed during inspection')
                content = data.decode('utf-8')
                return core._deny(event, json.dumps({'path': rel, 'sha256': inspected['sha256'],
                    'offset': offset, 'next_offset': min(offset + limit, len(content)),
                    'total_characters': len(content), 'text': content[offset:offset + limit]}, ensure_ascii=False))
            if action == 'inspect':
                paths = body.get('paths')
                if set(body) != {'paths'} or not isinstance(paths, list) or not 1 <= len(paths) <= 8:
                    raise ValueError('Inspect requires one to eight explicit paths')
                protected, _sid, _turn = hygiene_guard._identity({**payload, 'cwd': root})
                rows = []
                for raw in paths:
                    rel = hygiene_guard._rel(protected, raw)
                    rows.append({'path': rel, 'sha256': hygiene_guard._hash(protected, rel)})
                output = json.dumps({'inspected': rows}, ensure_ascii=False)
                if len(output) > 4000:
                    raise ValueError('Inspection response exceeds bound; inspect fewer paths')
                return core._deny(event, output + ' Inspection is not review approval.')
            handler = hygiene_guard.restore if action == 'restore' else hygiene_guard.review
            result = handler({**payload, 'cwd': root}, guard_state, body)
            if result:
                return result
            return core._deny(event, 'Hygiene review accepted by code. No shell command executed.')
        command = core._input(payload).get('command')
        parsed = core._parse_ledger_command(command)
        if parsed and parsed[0] == 'error':
            return core._deny(event, parsed[1])
        if parsed:
            return delegate()
        return core._deny(event, 'Strict hygiene: this shell command has no verified write boundary. Use supported file tools; no command executed.')
    if event == 'PreToolUse' and tool in core.EDIT_TOOLS:
        baseline = delegate()
        if baseline:
            return baseline
        ok, actual, root = core._protected_scope(payload, state)
        if not ok:
            return core._deny(event, actual)
        paths = core._input_paths(tool, core._input(payload))
        # The core validates paths in actual cwd. Preserve those exact absolute targets.
        targets = [str(Path(p).expanduser() if Path(p).expanduser().is_absolute()
                       else Path(actual) / p) for p in paths]
        return hygiene_guard.pre_edit({**payload, 'cwd': root}, guard_state, targets)
    if event == 'Stop':
        baseline = delegate()
        ok, actual, root = core._protected_scope(payload, state)
        if not ok:
            return {"decision": "block", "reason": "Hygiene root validation failed"}
        review = hygiene_guard.stop({**payload, "cwd": root}, guard_state)
        return review or baseline
    return delegate()
