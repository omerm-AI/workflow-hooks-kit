#!/usr/bin/env python3
"""Plugin bridge with exact global-command and source-byte deduplication."""
from __future__ import annotations
import json
from pathlib import Path
import shlex
import sys
import tool_scope_hook as core

EVENTS = {'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'Stop'}
ROOT = Path(__file__).resolve().parent.parent
MATCHER = 'Bash|apply_patch|Edit|Write|MultiEdit|NotebookEdit|Agent|spawn_agent'


def global_adapter_active(home: Path) -> bool:
    try:
        data = json.loads((home / '.claude/settings.json').read_text())
        if data.get('disableAllHooks') is True:
            return False
        script = home / '.claude/workflow-hooks-kit/bin/tool_scope_hook.py'
        expected = 'python3 -B ' + shlex.quote(str(script)) + ' --claude'
        for event in EVENTS:
            matcher = MATCHER if event in {'PreToolUse', 'PostToolUse'} else None
            if not any(group.get('matcher') == matcher and any(h.get('command') == expected for h in group.get('hooks', [])) for group in data.get('hooks', {}).get(event, [])):
                return False
        runtime_sources = ('tool_scope_hook.py', 'session_workflow_hook.py', 'hook_receipt.py', 'native_receipt.py', 'hygiene_guard.py', 'hygiene_adapter.py')
        return all((script.parent / name).read_bytes() == (ROOT / 'scripts' / name).read_bytes()
                   for name in runtime_sources)
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def _run(payload: dict, deduplicated: bool) -> dict:
    if deduplicated:
        return {}
    result = core.run(payload, claude=True)
    if payload.get('hook_event_name') == 'UserPromptSubmit':
        output = result.get('hookSpecificOutput', {})
        context = output.get('additionalContext')
        pointer = ' Use workflow-hooks-kit:work-standards for policy.'
        if isinstance(context, str) and len(context + pointer) <= 300:
            output['additionalContext'] = context + pointer
    return result


def run(payload: dict) -> dict:
    deduplicated = payload.get('hook_event_name') == 'SessionStart' or global_adapter_active(Path.home())
    return _run(payload, deduplicated)


def main() -> None:
    payload = None
    deduplicated = None
    handler_failed = False
    try:
        raw = sys.stdin.buffer.read(core.MAX_INPUT + 1)
        payload = json.loads(raw) if len(raw) <= core.MAX_INPUT else None
        if isinstance(payload, dict):
            deduplicated = payload.get('hook_event_name') == 'SessionStart' or global_adapter_active(Path.home())
            result = _run(payload, deduplicated)
        else:
            result = {}
    except Exception as exc:
        handler_failed = True
        result = {'systemMessage': f'Workflow plugin input error (fail-open): {type(exc).__name__}.'}
    if isinstance(payload, dict):
        event, tool = core._event(payload), core._tool_name(payload)
        if tool in {"exec_command", "shell_command"}:
            tool = "Bash"
        receipt_state = core.CLAUDE_STATE / 'hook-receipts' / 'plugin-adapter'
        components = (
            Path(__file__), Path(core.__file__), Path(core.workflow.__file__), Path(__file__).with_name("hygiene_guard.py"),
            Path(__file__).with_name("hygiene_adapter.py"),
        )
        try:
            import native_receipt
            components += (Path(__file__).with_name('hook_receipt.py'), Path(native_receipt.__file__))
            version = native_receipt.handler_version('claude-plugin-adapter-v1', components)
            if deduplicated:
                outcome = 'skipped'
            elif handler_failed:
                outcome = 'failure'
            else:
                outcome = native_receipt.outcome_for(result)
            native_receipt.create_native(receipt_state, payload, outcome, version)
        except Exception as exc:
            sys.stderr.write(f'Native hook receipt unavailable: {type(exc).__name__}.\n')
            denied = (isinstance(result, dict) and isinstance(result.get('hookSpecificOutput'), dict)
                      and result['hookSpecificOutput'].get('permissionDecision') == 'deny')
            if event == 'PreToolUse' and tool in core.EDIT_TOOLS | {'Bash'} and not denied:
                result = core._deny('PreToolUse', f'Hook receipt unavailable: {type(exc).__name__}; operation denied.')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
