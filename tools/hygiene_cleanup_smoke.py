#!/usr/bin/env python3
"""Disposable cleanup acceptance through installed hook commands, not native-client evidence."""
from __future__ import annotations
import argparse, hashlib, json, os, shlex, subprocess, sys, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = {
    'Assets/canonical.png': b'PNG fixture: canonical asset\n',
    'Assets/duplicate.png': b'PNG fixture: canonical asset\n',
    'design/helper.png': b'PNG fixture: unreferenced helper\n',
    'app.py': b"image = 'referenced.png'\n",
    'referenced.png': b'PNG fixture: referenced candidate\n',
    'Assets/referenced-canonical.png': b'PNG fixture: referenced candidate\n',
}

class CheckFailure(Exception):
    """A path-free acceptance failure."""

def digest(data): return hashlib.sha256(data).hexdigest()
def snapshot(project): return {rel: (p.read_bytes(), p.stat().st_mtime_ns) for rel in FIXTURES for p in [project / rel]}
def same_file(path, expected): return path.is_file() and (path.read_bytes(), path.stat().st_mtime_ns) == expected
def check(condition, name):
    if not condition: raise CheckFailure(name)

def exercise(home, platform, mode="enforce"):
    project = home / 'project-fixture'
    for rel, data in FIXTURES.items():
        path = project / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
    originals = snapshot(project)
    base = home / ('.codex' if platform == 'codex' else '.claude'); base.mkdir(mode=0o700)
    config = base / ('hooks.json' if platform == 'codex' else 'settings.json')
    foreign = {'type': 'command', 'command': 'foreign-readonly-observer'}
    original_config = {'hooks': {'PreToolUse': [{'matcher': 'Read', 'hooks': [foreign]}]}}
    config.write_text(json.dumps(original_config, indent=2) + '\n', encoding='utf-8')
    install = subprocess.run([sys.executable, str(ROOT / 'install.py'), '--platform', platform,
        '--home', str(home), '--hygiene-enforcement' if mode == 'enforce' else '--hygiene-file-tools'], cwd=ROOT, text=True, capture_output=True, timeout=60)
    check(install.returncode == 0, 'install_failed')
    check(all(same_file(project / rel, value) for rel, value in originals.items()) and not (project / 'Old').exists(), 'install_changed_existing_fixture')
    settings = json.loads(config.read_text(encoding='utf-8'))
    check(settings['hooks']['PreToolUse'][0] == original_config['hooks']['PreToolUse'][0], 'foreign_settings_not_preserved')
    commands = [h.get('command') for g in settings['hooks']['PreToolUse'] for h in g['hooks'] if 'workflow-hooks-kit/bin/tool_scope_hook.py' in h.get('command', '')]
    check(len(commands) == 1, 'installed_pretool_command_missing_or_duplicated')
    identity = {'session_id': 'fixture-' + uuid.uuid4().hex, 'cwd': str(project),
                ('turn_id' if platform == 'codex' else 'prompt_id'): 'cleanup-fixture-turn'}

    def call(action, body):
        payload = {**identity, 'hook_event_name': 'PreToolUse', 'tool_name': 'Bash',
                   'tool_input': {'command': 'workflow-hygiene ' + action + ' ' + shlex.quote(json.dumps(body))}}
        result = subprocess.run(shlex.split(commands[0]), input=json.dumps(payload), text=True,
            capture_output=True, timeout=20, env={**os.environ, 'HOME': str(home / 'caller-home')})
        check(result.returncode == 0, 'installed_callback_failed')
        return json.loads(result.stdout)

    def denied(result): return result.get('hookSpecificOutput', {}).get('permissionDecision') == 'deny'
    def review(rel, decision, canonical=None):
        data = originals[rel][0]
        entry = {'path': rel, 'decision': decision, 'sha256': digest(data),
            'reason': 'Disposable fixture cleanup acceptance with an explicit reviewed disposition.',
            'usage': 'Fixture usage and intended retained copy checked from the prepared project.',
            'dependencies': 'Local fixture references checked by the installed guard; no external dependencies.',
            'concurrency': 'One process owns a new private home and isolated fixture project.'}
        if canonical:
            entry.update(canonical=canonical, canonical_sha256=digest(originals[canonical][0]))
        return call('review', {'entries': [entry]})

    duplicate = review('Assets/duplicate.png', 'archive', 'Assets/canonical.png')
    check(denied(duplicate) and 'review accepted by code' in json.dumps(duplicate), 'duplicate_review_not_accepted')
    manifests = sorted((project / 'Old').rglob('manifest.json'))
    found = [p for p in manifests if json.loads(p.read_text()).get('original') == 'Assets/duplicate.png']
    check(len(found) == 1, 'duplicate_manifest_missing')
    duplicate_path = found[0]; record = json.loads(duplicate_path.read_text()); archived = project / record['archive']
    check(record.get('purpose') == 'reviewed-duplicate' and record.get('sha256') == digest(originals['Assets/duplicate.png'][0])
        and same_file(archived, originals['Assets/duplicate.png']) and not (project / 'Assets/duplicate.png').exists()
        and same_file(project / 'Assets/canonical.png', originals['Assets/canonical.png']), 'duplicate_archive_not_byte_exact')

    asset = review('design/helper.png', 'asset')
    check(denied(asset) and 'review accepted by code' in json.dumps(asset), 'asset_review_not_accepted')
    moved = [p for p in (project / 'Old').rglob('manifest.json') if json.loads(p.read_text()).get('original') == 'design/helper.png']
    check(len(moved) == 1, 'asset_manifest_missing')
    asset_record = json.loads(moved[0].read_text())
    check(asset_record.get('purpose') == 'asset-relocation' and same_file(project / 'Assets/design/helper.png', originals['design/helper.png'])
        and same_file(project / asset_record['archive'], originals['design/helper.png']) and not (project / 'design/helper.png').exists(), 'asset_transfer_not_byte_exact')

    archive_count = len(list((project / 'Old').rglob('manifest.json')))
    referenced = review('referenced.png', 'archive', 'Assets/referenced-canonical.png')
    check(denied(referenced) and 'local literal reference exists' in json.dumps(referenced)
        and same_file(project / 'referenced.png', originals['referenced.png']), 'referenced_media_was_not_refused')
    source = review('app.py', 'archive', 'Assets/canonical.png')
    check(denied(source) and 'unsupported archive candidate' in json.dumps(source)
        and same_file(project / 'app.py', originals['app.py']), 'source_archive_was_not_refused')
    check(len(list((project / 'Old').rglob('manifest.json'))) == archive_count, 'refused_review_created_archive')

    restored = call('restore', {'manifest': duplicate_path.relative_to(project).as_posix()})
    check(denied(restored) and 'review accepted by code' in json.dumps(restored)
        and same_file(project / 'Assets/duplicate.png', originals['Assets/duplicate.png']), 'duplicate_restore_failed')
    post = review('Assets/duplicate.png', 'keep')
    check(denied(post) and 'review accepted by code' in json.dumps(post), 'restored_file_review_failed')
    before = (project / 'Assets/duplicate.png').read_bytes()
    second = call('restore', {'manifest': duplicate_path.relative_to(project).as_posix()})
    check(denied(second) and 'restore never overwrites' in json.dumps(second)
        and (project / 'Assets/duplicate.png').read_bytes() == before, 'second_restore_overwrote_live_file')

    uninstall = subprocess.run([sys.executable, str(ROOT / 'install.py'), '--platform', platform,
        '--home', str(home), '--uninstall'], cwd=ROOT, text=True, capture_output=True, timeout=60)
    check(uninstall.returncode == 0, 'uninstall_failed')
    kit = base / 'workflow-hooks-kit'; policy = kit / ('state/hygiene-policy.json' if platform == 'codex' else 'hygiene-policy.json')
    check(json.loads(config.read_text(encoding='utf-8')) == original_config and (kit / 'bin/tool_scope_hook.py').is_file()
        and policy.is_file(), 'uninstall_did_not_retain_foreign_settings_and_recovery')
    return {'platform': platform, 'policy_mode': mode, 'checks': {'install_left_preexisting_files_unchanged': True,
        'reviewed_duplicate_archived_and_restored_exactly': True, 'unreferenced_asset_moved_to_Assets_with_recovery_copy': True,
        'referenced_media_and_required_source_refused': True, 'second_restore_refused_without_overwrite': True,
        'uninstall_retained_foreign_settings_and_recovery': True},
        'archive_count': len(list((project / 'Old').rglob('manifest.json')))}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', required=True, type=Path, help='New absolute disposable directory; must not exist')
    parser.add_argument('--platform', choices=('codex', 'claude', 'both'), default='both')
    parser.add_argument('--hygiene-mode', choices=('enforce', 'file-tools'), default='enforce')
    args = parser.parse_args(); home = args.home.expanduser(); resolved = home.resolve()
    unsafe = (Path.home().resolve(), ROOT.resolve())
    if not home.is_absolute() or home.exists() or home.is_symlink() or resolved == unsafe[0] or resolved == unsafe[1] or unsafe[1] in resolved.parents:
        parser.error('--home must be an absolute path to a new, non-existing disposable directory outside the account and repository')
    home.mkdir(mode=0o700, parents=True)
    platforms = ('codex', 'claude') if args.platform == 'both' else (args.platform,)
    try: results = [exercise(home / p, p, args.hygiene_mode) for p in platforms]
    except CheckFailure as exc:
        print(json.dumps({'status': 'fail', 'kind': 'installed-command-replay-not-native', 'model_calls': 0, 'check': str(exc)}, sort_keys=True)); return 1
    except Exception as exc:
        print(json.dumps({'status': 'fail', 'kind': 'installed-command-replay-not-native', 'model_calls': 0, 'check': 'unexpected_' + type(exc).__name__})); return 1
    print(json.dumps({'status': 'pass', 'kind': 'installed-command-replay-not-native', 'model_calls': 0, 'results': results}, indent=2)); return 0

if __name__ == '__main__': raise SystemExit(main())
