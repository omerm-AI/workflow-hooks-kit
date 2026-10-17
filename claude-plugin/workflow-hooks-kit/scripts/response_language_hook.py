#!/usr/bin/env python3
"""Small, fail-open Claude Code response-language context hook."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time

MAX_INPUT = 32_768
MAX_DIAGNOSTIC = 2_048
MAX_CONTEXT = 120
RECEIPT_MARKER_LENGTH = 49
CACHE_LIMIT = 512
CACHE_SCHEMA = 1
DIRECTIVES = {
    'he': 'ענה בעברית; קוד/קבצים/פקודות/Git באנגלית',
    'en': 'Reply in English; keep code/files/cmds/Git.',
}
EVENTS = {'UserPromptSubmit', 'SessionStart'}
IDENTITY_FIELDS = ('session_id', 'turn_id', 'prompt_id')
RECEIPT_UNAVAILABLE = 'Response-language receipt unavailable; directive emitted without receipt.'
SKIPPED_RECEIPT_UNAVAILABLE = 'Cached response-language receipt unavailable; no language context emitted.'


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


def _create_receipt(state_dir: str, event: str, payload: dict, outcome='success') -> str | None:
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
            state_dir, receipt_payload, outcome, _hook_version())
        return marker
    except Exception:
        return None


def _native_session(payload: dict) -> str | None:
    value = payload.get('session_id')
    if (not isinstance(value, str) or not value or len(value) > 256
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        return None
    return value


def _native_turn(payload: dict) -> str | None:
    prompt, turn = payload.get('prompt_id'), payload.get('turn_id')
    for value in (prompt, turn):
        if value is not None and (not isinstance(value, str) or not value or len(value) > 256
                                  or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            return None
    if prompt and turn and prompt != turn:
        return None
    return prompt or turn


@contextmanager
def _cache_lock(state_dir: str):
    directory = Path(state_dir)
    if directory.is_symlink():
        raise OSError('language state directory is a symlink')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise OSError('language state directory is not owner-only')
    fd = os.open(directory / '.language-cache.lock',
                 os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    locked = False
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise OSError('unsafe language cache lock')
        deadline = time.monotonic() + 2.0
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('language cache lock timed out')
                time.sleep(0.02)
        yield directory
    finally:
        if locked:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _cache_file(directory: Path, session: str) -> Path:
    return directory / ('language-session-' + _digest(session.encode('utf-8')) + '.json')


def _read_session_cache(directory: Path, session: str, language: str, version: str):
    """Return (matching, writable); unsafe paths are never followed or replaced."""
    path = _cache_file(directory, session)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False, True
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_size > CACHE_LIMIT):
        return False, False
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            opened = os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid()
                    or opened.st_mode & 0o077 or opened.st_size > CACHE_LIMIT):
                return False, False
            raw = os.read(fd, CACHE_LIMIT + 1)
        finally:
            os.close(fd)
        if len(raw) > CACHE_LIMIT:
            return False, True
        value = json.loads(raw.decode('ascii'))
        expected = {'schema': CACHE_SCHEMA, 'session_hash': _digest(session.encode('utf-8')),
                    'language': language, 'version_hash': version}
        return (isinstance(value, dict) and type(value.get('schema')) is int
                and value == expected), True
    except (OSError, UnicodeError, ValueError, TypeError):
        return False, True


def _write_session_cache(directory: Path, session: str, language: str, version: str) -> bool:
    path = _cache_file(directory, session)
    try:
        try:
            info = path.lstat()
        except FileNotFoundError:
            info = None
        if info is not None and (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                                 or info.st_mode & 0o077 or info.st_size > CACHE_LIMIT):
            return False
        value = {'schema': CACHE_SCHEMA, 'session_hash': _digest(session.encode('utf-8')),
                 'language': language, 'version_hash': version}
        encoded = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
        if len(encoded) > CACHE_LIMIT:
            return False
        fd, temporary = tempfile.mkstemp(prefix='.language-cache-', dir=directory)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return True
    except OSError:
        return False


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

        marker = None
        if args.state_dir:
            _diagnostic(args.state_dir, event, payload, directive)
            session = _native_session(payload)
            version = _hook_version()
            if event == 'UserPromptSubmit' and session and _native_turn(payload):
                try:
                    with _cache_lock(args.state_dir) as directory:
                        cached, writable = _read_session_cache(directory, session, args.language, version)
                        if cached:
                            # The prior local emission is cached; this receipt records suppression only.
                            skipped_marker = _create_receipt(args.state_dir, event, payload, 'skipped')
                            if skipped_marker:
                                print('{}')
                            else:
                                print(json.dumps({'systemMessage': SKIPPED_RECEIPT_UNAVAILABLE}))
                            return 0
                        marker = _create_receipt(args.state_dir, event, payload, 'success')
                        if marker and writable:
                            _write_session_cache(directory, session, args.language, version)
                except Exception:
                    # A cache failure cannot suppress a directive or create a cache entry.
                    marker = _create_receipt(args.state_dir, event, payload, 'success')
            else:
                # SessionStart always bootstraps, including resume/compact events.
                marker = _create_receipt(args.state_dir, event, payload, 'success')
                if event == 'SessionStart' and session and marker:
                    try:
                        with _cache_lock(args.state_dir) as directory:
                            _write_session_cache(directory, session, args.language, version)
                    except Exception:
                        pass
        context = directive
        output = {'hookSpecificOutput': {
            'hookEventName': event,
            'additionalContext': context,
        }}
        if args.state_dir:
            if marker and len(directive) + 1 + 4 + RECEIPT_MARKER_LENGTH + 1 <= MAX_CONTEXT:
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
