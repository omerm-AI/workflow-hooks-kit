#!/usr/bin/env python3
"""Disposable installed-command acceptance, not native-client/model evidence."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]


def exercise(home, platform):
    spec = importlib.util.spec_from_file_location('smoke_installer', ROOT / 'install.py')
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    base = home / ('.codex' if platform == 'codex' else '.claude')
    base.mkdir(mode=0o700, parents=True)
    config = base / ('hooks.json' if platform == 'codex' else 'settings.json')
    foreign = {'type': 'command', 'command': 'foreign-readonly-observer'}
    config.write_text(json.dumps({'hooks': {'PreToolUse': [{'matcher': 'Read', 'hooks': [foreign]}]}}))
    previous = home / 'existing-folder'
    previous.mkdir()
    (previous / 'current.txt').write_bytes(b'Original fixture bytes\n')
    (previous / 'required-source.txt').write_bytes(b'Keep required source unchanged\n')
    installer.operate(home, platform, hygiene_enforcement=True)
    installer.operate(home, platform, hygiene_enforcement=True)
    assert (previous / 'current.txt').read_bytes() == b'Original fixture bytes\n'
    assert not (previous / 'Old').exists(), 'Installer must not retroactively reorganize project files'
    caller_home = home / 'different-caller-home'
    caller_home.mkdir(mode=0o700)
    settings = json.loads(config.read_text())
    assert settings['hooks']['PreToolUse'][0] == {'matcher': 'Read', 'hooks': [foreign]}
    for event in installer.EVENTS:
        command = installer.command(home, platform)
        own = [h for g in settings['hooks'][event] for h in g['hooks'] if h.get('command') == command]
        assert len(own) == 1, 'Duplicate or missing owned handler'
    kit = base / 'workflow-hooks-kit'
    script = kit / 'bin/tool_scope_hook.py'
    results = []
    for kind in ('new-folder', 'existing-folder'):
        project = home / kind
        project.mkdir(exist_ok=True)
        original = b'Original fixture bytes\n'
        target = project / 'current.txt'
        target.write_bytes(original)
        canary = project / 'required-source.txt'
        canary.write_bytes(b'Keep required source unchanged\n')
        sid = 'smoke-' + uuid.uuid4().hex
        identity = {'session_id': sid, 'cwd': str(project),
                    ('turn_id' if platform == 'codex' else 'prompt_id'): 'smoke-turn'}

        def call(event, tool=None, body=None):
            payload = {**identity, 'hook_event_name': event}
            if tool:
                payload.update(tool_name=tool, tool_input=body or {})
            args = shlex.split(installer.command(home, platform))
            process = subprocess.run(args, input=json.dumps(payload), text=True,
                                     capture_output=True, timeout=15,
                                     env={**os.environ, 'HOME': str(caller_home)})
            assert process.returncode == 0, process.stderr
            return json.loads(process.stdout)

        def denied(result):
            return result.get('hookSpecificOutput', {}).get('permissionDecision') == 'deny'

        def sentinel(prefix, action, body):
            return call('PreToolUse', 'Bash', {'command': prefix + ' ' + action + ' ' + shlex.quote(json.dumps(body))})

        def review():
            body = {'entries': [{'path': 'current.txt', 'decision': 'keep',
                'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                'reason': 'Current disposable acceptance file', 'usage': 'Explicit fixture output',
                'dependencies': 'Standalone controlled fixture; canary retained',
                'concurrency': 'Single smoke process in a newly created private home'}]}
            result = sentinel('workflow-hygiene', 'review', body)
            assert denied(result) and 'review accepted by code' in json.dumps(result)

        assert denied(sentinel('workflow-ledger', 'plan', {
            'definition_of_done': 'Update controlled fixture', 'outputs': ['current.txt'],
            'qa': {'check': 'Compare exact current and Old bytes', 'expected': 'Updated fixture bytes'}}))
        edit = {'file_path': str(target), 'content': 'Updated fixture bytes\n'}
        assert denied(call('PreToolUse', 'Write', edit))
        assert not (project / 'Old').exists()
        inspection = sentinel('workflow-hygiene', 'read', {'path': 'current.txt', 'limit': 100})
        assert denied(inspection) and 'Original fixture bytes' in json.dumps(inspection)
        assert denied(call('PreToolUse', 'Write', edit)), 'Inspection must not grant approval'
        review()
        assert call('PreToolUse', 'Write', edit) == {}
        manifests = list((project / 'Old').rglob('manifest.json'))
        assert len(manifests) == 1
        record = json.loads(manifests[0].read_text())
        assert (project / record['archive']).read_bytes() == original
        # This explicit harness write is NOT a native-client tool invocation.
        target.write_text('Updated fixture bytes\n')
        call('PostToolUse', 'Write', edit)
        assert denied(call('PreToolUse', 'Write', {'file_path': str(project / 'next.txt'), 'content': 'No'}))
        assert not (project / 'next.txt').exists()
        assert call('Stop').get('decision') == 'block'
        for tool in ('mcp__filesystem__write_file', 'mcp.fake.exec_command', 'functions.exec', 'write_stdin'):
            assert denied(call('PreToolUse', tool, {'path': 'next.txt', 'cmd': 'touch next.txt'}))
        for command in ('pwd', 'git status', 'touch next.txt'):
            assert denied(call('PreToolUse', 'Bash', {'command': command}))
        review()
        qa = sentinel('workflow-ledger', 'qa', {'state': 'complete', 'qa': {
            'evidence': 'Harness compared actual new output, exact Old bytes and retained canary',
            'verdict': 'pass', 'reviewer_id': 'lead'}})
        assert denied(qa) and 'QA saved' in json.dumps(qa)
        assert call('Stop') == {}
        assert canary.read_bytes() == b'Keep required source unchanged\n'
        assert not (caller_home / '.codex').exists() and not (caller_home / '.claude').exists(), 'Hook state escaped installation home'
        results.append({'folder': kind, 'beforeimage': True, 'next_edit_denied': True,
                        'stop_block_and_release': True, 'unknown_tools_denied': True,
                        'required_source_unchanged': True})
    installer.operate(home, platform, uninstall=True)
    restored = json.loads(config.read_text())
    assert restored == {'hooks': {'PreToolUse': [{'matcher': 'Read', 'hooks': [foreign]}]}}
    assert (kit / 'bin/tool_scope_hook.py').exists(), 'Recovery runtime must be retained'
    return {'platform': platform, 'idempotent_install': True, 'foreign_settings_preserved': True,
            'uninstall_preserves_recovery': True, 'cases': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True, help='New absolute disposable directory; must not exist')
    parser.add_argument('--platform', choices=('codex', 'claude', 'both'), default='both')
    args = parser.parse_args()
    home = args.home.expanduser()
    if not home.is_absolute() or home.exists() or home.is_symlink():
        parser.error('--home must be a new absolute disposable directory, never an existing account home')
    home.mkdir(mode=0o700, parents=True)
    platforms = ('codex', 'claude') if args.platform == 'both' else (args.platform,)
    results = [exercise(home / platform, platform) for platform in platforms]
    print(json.dumps({'status': 'pass', 'kind': 'installed-command-replay-not-native',
                      'model_calls': 0, 'results': results}, indent=2))


if __name__ == '__main__':
    main()
