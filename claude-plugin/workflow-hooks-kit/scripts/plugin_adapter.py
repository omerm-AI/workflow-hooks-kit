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
MATCHER = 'Bash|apply_patch|Edit|Write|MultiEdit|NotebookEdit'


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
        return all((script.parent / name).read_bytes() == (ROOT / 'scripts' / name).read_bytes() for name in ('tool_scope_hook.py', 'session_workflow_hook.py'))
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def run(payload: dict) -> dict:
    if global_adapter_active(Path.home()) or payload.get('hook_event_name') == 'SessionStart':
        return {}
    result = core.run(payload, claude=True)
    if payload.get('hook_event_name') == 'UserPromptSubmit':
        output = result.get('hookSpecificOutput', {})
        context = output.get('additionalContext')
        pointer = ' Use workflow-hooks-kit:work-standards for policy.'
        if isinstance(context, str) and len(context + pointer) <= 300:
            output['additionalContext'] = context + pointer
    return result


def main() -> None:
    try:
        raw = sys.stdin.buffer.read(core.MAX_INPUT + 1)
        payload = json.loads(raw) if len(raw) <= core.MAX_INPUT else None
        result = run(payload) if isinstance(payload, dict) else {}
    except Exception as exc:
        result = {'systemMessage': f'Workflow plugin input error (fail-open): {type(exc).__name__}.'}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
