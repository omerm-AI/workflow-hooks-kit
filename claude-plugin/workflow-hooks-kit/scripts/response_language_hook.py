#!/usr/bin/env python3
"""Small, fail-open Claude Code response-language context hook."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

MAX_INPUT = 32_768
MAX_DIAGNOSTIC = 2_048
MAX_CONTEXT = 120
RECEIPT_MARKER_LENGTH = 49
DIRECTIVES = {
    'he': 'ענה בעברית; קוד/קבצים/פקודות/Git באנגלית',
    'en': 'Reply in English; keep code/files/cmds/Git.',
}
EVENTS = {'UserPromptSubmit', 'SessionStart'}
IDENTITY_FIELDS = ('session_id', 'turn_id', 'prompt_id')
RECEIPT_UNAVAILABLE = 'Response-language receipt unavailable; directive emitted without receipt.'


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hook_version() -> str:
    script = Path(__file__).read_bytes()
    helper = Path(__file__).with_name('hook_receipt.py').read_bytes()
    return _digest(script + helper)


def _diagnostic(state_dir: str, event: str, payload: dict, directive: str) -> None:
    """Write bounded metadata only; diagnostic failures never affect hook output."""
    try:
        directory = Path(state_dir)
        if directory.is_symlink():
            return
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            return
        target = directory / 'response-language.json'
        if target.is_symlink():
            return
        if target.exists():
            target_info = target.lstat()
            if (not stat.S_ISREG(target_info.st_mode) or target_info.st_uid != os.getuid()
                    or target_info.st_mode & 0o077 or target_info.st_size > MAX_DIAGNOSTIC):
                return
        identities = {}
        for key in IDENTITY_FIELDS:
            value = payload.get(key)
            if isinstance(value, str) and value:
                identities[key] = _digest(value.encode('utf-8', 'replace'))
        record = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'event': event,
            'identity_hashes': identities,
            'hook_version_hash': _hook_version(),
            'directive_hash': _digest(directive.encode('utf-8')),
        }
        encoded = (json.dumps(record, sort_keys=True, separators=(',', ':')) + '\n').encode()
        if len(encoded) > MAX_DIAGNOSTIC:
            return
        fd, temporary = tempfile.mkstemp(prefix='.response-language-', dir=directory)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(encoded)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    except (OSError, ValueError, TypeError):
        return


def _create_receipt(state_dir: str, event: str, payload: dict) -> str | None:
    """Import the local receipt helper only for explicitly enabled diagnostics."""
    if event not in EVENTS:
        return None
    try:
        script_dir = str(Path(__file__).resolve().parent)
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        import hook_receipt

        receipt_payload = {'event': event, 'session_id': payload.get('session_id')}
        for field in ('turn_id', 'prompt_id'):
            if field in payload:
                receipt_payload[field] = payload[field]
        marker, _receipt = hook_receipt.create(
            state_dir, receipt_payload, 'success', _hook_version())
        return marker
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language', help='Response language code: he or en. Omit to disable.')
    parser.add_argument('--state-dir', help='Optional owner-only directory for signed receipts and diagnostics.')
    args = parser.parse_args()
    directive = DIRECTIVES.get(args.language)
    if not directive or len(directive) > MAX_CONTEXT:
        print('{}')
        return 0
    try:
        encoded_input = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(encoded_input) > MAX_INPUT:
            print('{}')
            return 0
        payload = json.loads(encoded_input.decode('utf-8'))
        if not isinstance(payload, dict):
            print('{}')
            return 0
        event = payload.get('hook_event_name')
        # Agent events inherit the parent process; don't impose a user preference on them.
        if 'agent_id' in payload or event not in EVENTS:
            print('{}')
            return 0

        context = directive
        output = {'hookSpecificOutput': {
            'hookEventName': event,
            'additionalContext': context,
        }}
        if args.state_dir:
            _diagnostic(args.state_dir, event, payload, directive)
            if len(directive) + 1 + 4 + RECEIPT_MARKER_LENGTH + 1 <= MAX_CONTEXT:
                marker = _create_receipt(args.state_dir, event, payload)
            else:
                marker = None
            if marker:
                context += ' [wf:' + marker + ']'
            else:
                output['systemMessage'] = RECEIPT_UNAVAILABLE
            output['hookSpecificOutput']['additionalContext'] = context
        print(json.dumps(output, ensure_ascii=False))
        return 0
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        print('{}')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
