#!/usr/bin/env python3
"""Install or uninstall a reversible Claude Code response-language hook."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import stat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from install import MAX_CONFIG, bounded_json, installation_lock, safe_path, write_json  # noqa: E402

SOURCE = ROOT / 'claude-plugin/workflow-hooks-kit/scripts/response_language_hook.py'
HELPER_SOURCE = ROOT / 'claude-plugin/workflow-hooks-kit/scripts/hook_receipt.py'
RUNTIME_NAMES = ('response_language_hook.py', 'hook_receipt.py')
EVENTS = ('SessionStart', 'UserPromptSubmit')
RECEIPT_LIMIT = 64_000


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_receipt(path: Path) -> dict:
    data = bounded_json(path, RECEIPT_LIMIT)
    if not isinstance(data.get('owned', {}), dict):
        raise ValueError('Invalid response-language ownership receipt.')
    for event, item in data.get('owned', {}).items():
        if event not in EVENTS or not isinstance(item, dict) or not isinstance(item.get('hook'), dict):
            raise ValueError('Invalid response-language ownership receipt.')
    hashes = data.get('runtime_hashes')
    if hashes is not None and (not isinstance(hashes, dict)
            or any(name not in RUNTIME_NAMES or not isinstance(value, str)
                   for name, value in hashes.items())):
        raise ValueError('Invalid response-language runtime ownership hashes.')
    return data


def _groups(data: dict) -> dict:
    hooks = data.get('hooks', {})
    if not isinstance(hooks, dict):
        raise ValueError('Claude hooks must be an object; no changes made.')
    for event, groups in hooks.items():
        if not isinstance(groups, list) or any(
                not isinstance(group, dict) or not isinstance(group.get('hooks'), list)
                or any(not isinstance(hook, dict) for hook in group['hooks']) for group in groups):
            raise ValueError(f'Invalid hook groups for {event}; no changes made.')
    return hooks


def _backup(target: Path, backup_dir: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    if target.exists():
        backup = backup_dir / f'{stamp}-settings.json'
        with backup.open('xb') as stream:
            stream.write(target.read_bytes())
    else:
        backup = backup_dir / f'{stamp}-settings.absent'
        with backup.open('x', encoding='utf-8') as stream:
            stream.write('settings.json did not exist\n')
    return backup



def _snapshot(path: Path):
    if not path.exists():
        return None
    return path.read_bytes(), stat.S_IMODE(path.stat().st_mode)


def _restore(path: Path, snapshot) -> None:
    if snapshot is None:
        path.unlink(missing_ok=True)
        return
    content, mode = snapshot
    fd, temporary = tempfile.mkstemp(prefix='.response-language-rollback-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _owned_runtime_hash(receipt: dict, name: str):
    hashes = receipt.get('runtime_hashes')
    if isinstance(hashes, dict) and name in hashes:
        return hashes[name]
    if name == 'response_language_hook.py':
        return receipt.get('runtime_hash')
    return None


def _validate_runtime(source: Path, destination: Path, receipt: dict, name: str) -> str:
    safe_path(destination)
    safe_path(destination.parent, True)
    source_hash = _hash(source)
    if destination.exists():
        current_hash = _hash(destination)
        owned_hash = _owned_runtime_hash(receipt, name)
        if current_hash != source_hash and current_hash != owned_hash:
            raise ValueError(f'A different {name} already exists; preserved without replacement.')
    return source_hash


def _write_runtime(source: Path, destination: Path, receipt: dict, name: str) -> str:
    safe_path(destination)
    safe_path(destination.parent, True)
    source_hash = _hash(source)
    if destination.exists():
        current_hash = _hash(destination)
        owned_hash = _owned_runtime_hash(receipt, name)
        if current_hash != source_hash and current_hash != owned_hash:
            raise ValueError(f'A different {name} already exists; preserved without replacement.')
        if current_hash == source_hash:
            return source_hash
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup_dir = destination.parent.parent / 'backups'
        safe_path(backup_dir, True)
        backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (backup_dir / f'{stamp}-{name}').open('xb') as stream:
            stream.write(destination.read_bytes())
    fd, temporary = tempfile.mkstemp(prefix='.response-language-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(source.read_bytes())
        os.chmod(temporary, 0o700)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return source_hash


def configure(home: Path, language: str | None, uninstall: bool) -> dict:
    if not uninstall and language not in {'he', 'en'}:
        raise ValueError('Choose --language he or --language en.')
    base = home / '.claude'
    target = base / 'settings.json'
    kit = base / 'workflow-hooks-kit'
    binaries = kit / 'bin'
    receipt_path = kit / 'response-language-receipt.json'
    backup_dir = kit / 'backups'
    safe_path(base, True)
    safe_path(target)
    safe_path(kit, True)
    safe_path(binaries, True)
    safe_path(receipt_path)
    safe_path(backup_dir, True)
    if uninstall and not receipt_path.exists():
        return {'action': 'uninstalled', 'config_changed': False, 'backup': None,
                'runtime': str(binaries / 'response_language_hook.py')}
    if target.exists() and target.stat().st_size > MAX_CONFIG:
        raise ValueError('Claude settings exceed the 4 MB safety limit.')
    if kit.exists():
        for directory, dirs, files in os.walk(kit, followlinks=False):
            for name in dirs:
                safe_path(Path(directory) / name, True)
            for name in files:
                safe_path(Path(directory) / name)
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    with installation_lock(base):
        # Recheck paths and size after waiting for another local installer.
        safe_path(target)
        safe_path(kit, True)
        if target.exists() and target.stat().st_size > MAX_CONFIG:
            raise ValueError('Claude settings exceed the 4 MB safety limit.')
        receipt = _read_receipt(receipt_path)
        owned = receipt.get('owned', {})
        data = bounded_json(target, MAX_CONFIG)
        hooks = _groups(data)
        changed = json.loads(json.dumps(data))
        changed_hooks = changed.setdefault('hooks', {})
        new_owned = {} if uninstall else dict(owned)
        runtime_paths = {name: binaries / name for name in RUNTIME_NAMES}
        receipt_state = kit / 'language-receipts'
        runtime_hashes = {name: _owned_runtime_hash(receipt, name) for name in RUNTIME_NAMES}

        if not uninstall:
            hook_runtime = runtime_paths['response_language_hook.py']
            command = ('python3 -B ' + shlex.quote(str(hook_runtime)) + ' --language ' + language
                       + ' --state-dir ' + shlex.quote(str(receipt_state)))
            handler = {'type': 'command', 'command': command, 'timeout': 5}
            for event in EVENTS:
                expected = {'hooks': [handler]}
                existing_owner = owned.get(event)
                groups = changed_hooks.get(event, [])
                if existing_owner:
                    old_handler = existing_owner['hook']
                    matched = False
                    for group in groups:
                        if group.get('matcher') is None and old_handler in group['hooks']:
                            matched = True
                            if old_handler != handler:
                                group['hooks'] = [handler if item == old_handler else item for item in group['hooks']]
                            break
                    if not matched:
                        raise ValueError(f'Owned {event} handler changed or disappeared; preserved without replacement.')
                    new_owned[event] = {'hook': handler}
                    continue
                if any(handler in group['hooks'] for group in groups):
                    raise ValueError(f'An identical unowned {event} handler already exists; refusing to claim it.')
                groups.append(expected)
                changed_hooks[event] = groups
                new_owned[event] = {'hook': handler}
        else:
            for event, owner in owned.items():
                groups = changed_hooks.get(event, [])
                removed = False
                kept_groups = []
                for group in groups:
                    group_hooks = list(group['hooks'])
                    if not removed and group.get('matcher') is None and owner['hook'] in group_hooks:
                        group_hooks.remove(owner['hook'])
                        removed = True
                        if group_hooks:
                            kept_groups.append({**group, 'hooks': group_hooks})
                        elif len(group) > 1:
                            kept_groups.append({**group, 'hooks': []})
                    else:
                        kept_groups.append(group)
                if kept_groups:
                    changed_hooks[event] = kept_groups
                elif event in changed_hooks:
                    changed_hooks.pop(event)
            if not changed_hooks and not hooks:
                changed.pop('hooks', None)

        if not uninstall:
            runtime_hashes = {
                name: _validate_runtime(ROOT / 'claude-plugin/workflow-hooks-kit/scripts' / name,
                                        runtime_paths[name], receipt, name)
                for name in RUNTIME_NAMES
            }
        config_changed = changed != data
        backup = None
        next_receipt = {
            'platform': 'claude-code',
            'owned': new_owned,
            'runtime_hash': runtime_hashes.get('response_language_hook.py'),
            'runtime_hashes': runtime_hashes,
            'uninstalled': uninstall,
            'last_backup': None,
        }
        runtime_before = {name: _snapshot(path) for name, path in runtime_paths.items()} if not uninstall else {}
        config_before = _snapshot(target)
        receipt_before = _snapshot(receipt_path)
        runtime_touched = []
        config_touched = receipt_touched = False
        try:
            kit.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not uninstall:
                binaries.mkdir(parents=True, exist_ok=True, mode=0o700)
            if config_changed:
                backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                backup = _backup(target, backup_dir)
                next_receipt['last_backup'] = str(backup)
            else:
                next_receipt['last_backup'] = receipt.get('last_backup')
            if not uninstall:
                for name in RUNTIME_NAMES:
                    runtime_touched.append(name)
                    _write_runtime(ROOT / 'claude-plugin/workflow-hooks-kit/scripts' / name,
                                   runtime_paths[name], receipt, name)
            if config_changed:
                config_touched = True
                write_json(target, changed)
            receipt_touched = True
            write_json(receipt_path, next_receipt)
        except Exception as failure:
            # Recover exact file bytes if any atomic replacement failed mid-transaction.
            # Retain the settings beforeimage backup for manual recovery evidence.
            rollback_errors = []
            for touched, path, before in (
                    (receipt_touched, receipt_path, receipt_before),
                    (config_touched, target, config_before)):
                if touched:
                    try:
                        _restore(path, before)
                    except Exception as error:
                        rollback_errors.append(f'{path.name}: {error}')
            for name in reversed(runtime_touched):
                try:
                    _restore(runtime_paths[name], runtime_before[name])
                except Exception as error:
                    rollback_errors.append(f'{name}: {error}')
            if rollback_errors:
                raise RuntimeError('Install failed and rollback was incomplete: ' + '; '.join(rollback_errors)) from failure
            raise
        return {'action': 'uninstalled' if uninstall else 'installed',
                'config_changed': config_changed, 'backup': str(backup) if backup else None,
                'runtime': [str(path) for path in runtime_paths.values()]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home(), help='Alternate home for isolated setup or testing.')
    parser.add_argument('--language', choices=('he', 'en'), help='Required for installation.')
    parser.add_argument('--uninstall', action='store_true', help='Remove unchanged owned handlers only.')
    args = parser.parse_args()
    try:
        result = configure(args.home, args.language, args.uninstall)
    except RuntimeError as exc:
        print(f'Install failed; inspect settings, receipt, runtime, and backups: {exc}', file=sys.stderr)
        return 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'Configuration unchanged: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
