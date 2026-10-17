#!/usr/bin/env python3
"""Install a companion native delegation gate beside a trusted legacy kit core."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from install import MAX_CONFIG, bounded_json, installation_lock, read_config, safe_path, write_json  # noqa: E402

SOURCE = ROOT / 'claude-plugin/workflow-hooks-kit/scripts'
MODULES = ('delegation_gate.py', 'delegation_guard.py', 'hook_receipt.py', 'delegation_binding.py')
MODEL_POLICY = 'model-policy.json'
MAX_MODEL_POLICY = 8_192


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON object keys are unsupported.')
        result[key] = value
    return result
MATCHER = 'Agent|spawn_agent'
EVENT = 'PreToolUse'
RECEIPT = 'delegation-guard-receipt.json'
RECEIPT_LIMIT = 64_000


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _snapshot(path: Path):
    if not path.exists():
        return None
    safe_path(path)
    return path.read_bytes(), stat.S_IMODE(path.stat().st_mode)


def _restore(path: Path, snapshot):
    if snapshot is None:
        path.unlink(missing_ok=True)
        return
    data, mode = snapshot
    fd, temporary = tempfile.mkstemp(prefix='.delegation-rollback-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_bytes(path: Path, data: bytes, mode: int = 0o700):
    safe_path(path)
    fd, temporary = tempfile.mkstemp(prefix='.delegation-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_receipt(path: Path) -> dict:
    receipt = bounded_json(path, RECEIPT_LIMIT)
    if not receipt:
        return {}
    if type(receipt.get('version')) is not int or receipt.get('version') != 1 or not isinstance(receipt.get('runtime'), dict):
        raise ValueError('Invalid delegation guard ownership receipt.')
    owned = receipt.get('owned')
    if not isinstance(owned, dict) or owned.get('event') != EVENT or owned.get('matcher') != MATCHER or not isinstance(owned.get('hook'), dict):
        raise ValueError('Invalid delegation guard ownership receipt.')
    for name, item in receipt['runtime'].items():
        if name not in (*MODULES, MODEL_POLICY) or not isinstance(item, dict) or not isinstance(item.get('sha256'), str) or not isinstance(item.get('created'), bool):
            raise ValueError('Invalid delegation guard runtime receipt.')
    return receipt


def _groups(data: dict) -> dict:
    hooks = data.get('hooks', {})
    if not isinstance(hooks, dict):
        raise ValueError('Hooks must be an object; no changes made.')
    for event, groups in hooks.items():
        if not isinstance(groups, list) or any(
                not isinstance(group, dict) or not isinstance(group.get('hooks'), list)
                or any(not isinstance(hook, dict) for hook in group['hooks']) for group in groups):
            raise ValueError(f'Invalid hook groups for {event}; no changes made.')
    return hooks


def _validate_core(core_dir: Path):
    if not core_dir.is_absolute() or core_dir.is_symlink() or not core_dir.is_dir():
        raise ValueError('Trusted core directory must be a real directory.')
    for name in ('tool_scope_hook.py', 'session_workflow_hook.py'):
        path = core_dir / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Trusted core directory must contain regular core and workflow scripts.')
    source = (core_dir / 'tool_scope_hook.py').read_text(encoding='utf-8')
    if 'delegation_gate' in source or 'DELEGATION_TOOLS' in source or 'spawn_agent' in source:
        raise ValueError('Delegation is already covered by the selected core; refusing duplicate guard.')


def _command(runtime: Path, core_dir: Path, platform: str, strict: bool = False) -> str:
    result = 'python3 -B ' + shlex.quote(str(runtime)) + ' --core-dir ' + shlex.quote(str(core_dir))
    if platform == 'claude':
        result += ' --claude'
    if strict:
        result += ' --model-map ' + shlex.quote(str(runtime.parent / MODEL_POLICY))
    return result


def _read_model_policy(path: Path) -> bytes:
    path = Path(path).expanduser()
    if path.is_symlink():
        raise ValueError('Model policy must be a regular owner-only file.')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > MAX_MODEL_POLICY):
            raise ValueError('Model policy must be a bounded owner-only regular file.')
        chunks = []
        remaining = MAX_MODEL_POLICY + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 4096))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b''.join(chunks)
    finally:
        os.close(fd)
    if len(raw) > MAX_MODEL_POLICY:
        raise ValueError('Model policy exceeds 8 KiB.')
    try:
        value = json.loads(raw.decode('utf-8', 'strict'), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Model policy must be strict UTF-8 JSON.') from exc
    if type(value) is not dict or set(value) != {'schema', 'models'}:
        raise ValueError('Model policy must contain exactly schema and models.')
    if type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('Model policy schema must be integer 1.')
    models = value['models']
    if type(models) is not dict or not models or len(models) > 16:
        raise ValueError('Model policy must contain 1 to 16 aliases.')
    for alias, native_id in models.items():
        for label in (alias, native_id):
            if (not isinstance(label, str) or not label or len(label) > 256
                    or not label.isascii() or any(ch.isspace() or ord(ch) < 33 or ord(ch) == 127 for ch in label)):
                raise ValueError('Model aliases and native IDs must be bounded printable ASCII without whitespace.')
    return raw


def _backup(target: Path, backup_dir: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = backup_dir / f'{stamp}-{target.name}'
    content = target.read_bytes() if target.exists() else b'{"config_was_absent": true}\n'
    with path.open('xb') as stream:
        stream.write(content)
    os.chmod(path, 0o600)
    return path


def configure(home: Path, platform: str, core_dir: Path, uninstall: bool = False,
              model_map: Path | None = None) -> dict:
    if platform not in {'codex', 'claude'}:
        raise ValueError('Platform must be codex or claude.')
    if model_map is not None and platform != 'claude':
        raise ValueError('Strict stage packets are supported only by the Claude hook contract.')
    policy_data = None if uninstall or model_map is None else _read_model_policy(model_map)
    home = Path(home).expanduser()
    core_dir = Path(core_dir).expanduser()
    _validate_core(core_dir)
    base = home / ('.codex' if platform == 'codex' else '.claude')
    target = base / ('hooks.json' if platform == 'codex' else 'settings.json')
    kit = base / 'workflow-hooks-kit'
    binaries = kit / 'bin'
    runtime_dir = binaries / 'delegation-guard'
    state_dir = kit / 'delegation-receipts'
    backup_dir = kit / 'backups'
    receipt_path = kit / RECEIPT
    for path, directory in ((base, True), (target, False), (kit, True), (binaries, True),
                            (runtime_dir, True), (state_dir, True),
                            (backup_dir, True), (receipt_path, False),
                            (base / '.workflow-hooks-kit-install.lock', False)):
        safe_path(path, directory)
    if kit.exists():
        for directory, dirs, files in os.walk(kit, followlinks=False):
            for name in dirs:
                safe_path(Path(directory) / name, True)
            for name in files:
                safe_path(Path(directory) / name)
    for name in MODULES:
        safe_path(SOURCE / name)
        if not (SOURCE / name).is_file():
            raise ValueError(f'Missing companion module: {name}')

    pre_receipt = _read_receipt(receipt_path)
    if (not uninstall and model_map is None
            and MODEL_POLICY in pre_receipt.get('runtime', {})):
        _read_model_policy(runtime_dir / MODEL_POLICY)

    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    with installation_lock(base):
        for path, directory in ((target, False), (kit, True), (binaries, True), (runtime_dir, True),
                                (state_dir, True), (backup_dir, True), (receipt_path, False)):
            safe_path(path, directory)
        if state_dir.exists():
            info = state_dir.stat()
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError('Delegation receipt state must be mode 0700 and owned by this user.')
        if target.exists() and target.stat().st_size > MAX_CONFIG:
            raise ValueError('Hook configuration exceeds the 4 MB safety limit.')
        receipt = _read_receipt(receipt_path)
        data = read_config(target)
        hooks = _groups(data)
        previous_owner = receipt.get('owned')
        if receipt and receipt.get('platform') != platform:
            raise ValueError('Delegation guard receipt belongs to a different platform.')
        runtime_path = runtime_dir / 'delegation_guard.py'
        strict = model_map is not None or MODEL_POLICY in receipt.get('runtime', {})
        if not uninstall and model_map is None and strict:
            _read_model_policy(runtime_dir / MODEL_POLICY)
        expected_hook = {'type': 'command', 'command': _command(runtime_path, core_dir, platform, strict) +
                         ' --state-dir ' + shlex.quote(str(state_dir)), 'timeout': 10}
        upgrade_from_legacy = False
        if previous_owner and previous_owner.get('matcher') != MATCHER:
            raise ValueError('Owned delegation command changed; preserved without replacement.')
        if previous_owner and previous_owner.get('hook') != expected_hook:
            legacy_hook = {'type': 'command', 'command': _command(runtime_path, core_dir, platform) +
                           ' --state-dir ' + shlex.quote(str(state_dir)), 'timeout': 10}
            upgrade_from_legacy = bool(model_map is not None and previous_owner.get('hook') == legacy_hook)
            if not upgrade_from_legacy:
                raise ValueError('Owned delegation command changed; preserved without replacement.')
        current_groups = hooks.get(EVENT, [])
        owned_group = None
        if previous_owner:
            for group in current_groups:
                if group.get('matcher') == MATCHER and previous_owner['hook'] in group['hooks']:
                    owned_group = group
                    break
            if owned_group is None:
                raise ValueError('Owned delegation hook changed or disappeared; preserved for review.')
        elif uninstall:
            return {'action': 'uninstalled', 'platform': platform, 'config': str(target),
                    'runtime': str(runtime_path), 'backup': None}
        if not uninstall:
            for group in current_groups:
                if group is not owned_group and any(hook.get('command') == expected_hook['command'] for hook in group['hooks']):
                    raise ValueError('Delegation command already exists without this installer receipt.')

        changed = json.loads(json.dumps(data))
        changed_hooks = changed.setdefault('hooks', {})
        groups = changed_hooks.setdefault(EVENT, [])
        runtime_receipt = dict(receipt.get('runtime', {}))
        runtime_snapshots = {}
        module_data = {name: (SOURCE / name).read_bytes() for name in MODULES}
        if policy_data is not None:
            module_data[MODEL_POLICY] = policy_data
        managed_modules = tuple(dict.fromkeys((*MODULES, *receipt.get('runtime', {}), *module_data)))
        created_dirs = []
        backup_paths = []
        if not binaries.exists() and not uninstall:
            binaries.mkdir(parents=True, mode=0o700)
            created_dirs.append(binaries)
        if not runtime_dir.exists() and not uninstall:
            runtime_dir.mkdir(parents=True, mode=0o700)
            created_dirs.append(runtime_dir)
        if not state_dir.exists() and not uninstall:
            state_dir.mkdir(parents=True, mode=0o700)
            created_dirs.append(state_dir)
        if not backup_dir.exists() and not uninstall:
            backup_dir.mkdir(parents=True, mode=0o700)
            created_dirs.append(backup_dir)
        if not kit.exists():
            kit.mkdir(parents=True, mode=0o700)
            created_dirs.append(kit)
        if not backup_dir.exists() and (not uninstall or target.exists()):
            backup_dir.mkdir(parents=True, mode=0o700)
            created_dirs.append(backup_dir)

        config_snapshot = _snapshot(target)
        receipt_snapshot = _snapshot(receipt_path)
        for name in managed_modules:
            runtime = runtime_dir / name
            runtime_snapshots[runtime] = _snapshot(runtime)
        try:
            if not uninstall:
                for name, owner in runtime_receipt.items():
                    if name in module_data:
                        continue
                    runtime = runtime_dir / name
                    safe_path(runtime)
                    if (not runtime.is_file() or _sha256(runtime.read_bytes()) != owner['sha256']):
                        raise ValueError(f'Owned companion file changed; preserved without replacement: {name}')
            if uninstall:
                if previous_owner:
                    new_groups = []
                    removed_owned = False
                    for group in groups:
                        is_owned = (not removed_owned and group.get('matcher') == MATCHER
                                    and previous_owner['hook'] in group['hooks'])
                        if is_owned:
                            removed_owned = True
                            kept = [hook for hook in group['hooks'] if hook != previous_owner['hook']]
                            if kept:
                                new_groups.append({**group, 'hooks': kept})
                        else:
                            new_groups.append(group)
                    changed_hooks[EVENT] = new_groups
                    if not new_groups and not receipt.get('original_had_event', False):
                        changed_hooks.pop(EVENT, None)
                    if not changed_hooks and not receipt.get('original_had_hooks', False):
                        changed.pop('hooks', None)
            else:
                if not previous_owner:
                    groups.append({'matcher': MATCHER, 'hooks': [expected_hook]})
                elif upgrade_from_legacy:
                    matches = [group for group in groups if group.get('matcher') == MATCHER
                               and previous_owner['hook'] in group['hooks']]
                    if len(matches) != 1:
                        raise ValueError('Owned delegation handler changed during strict upgrade.')
                    hooks_list = matches[0]['hooks']
                    hooks_list[hooks_list.index(previous_owner['hook'])] = expected_hook
                for name in module_data:
                    runtime = runtime_dir / name
                    source_bytes = module_data[name]
                    source_hash = _sha256(source_bytes)
                    old = runtime_receipt.get(name)
                    if runtime.exists():
                        current_hash = _sha256(runtime.read_bytes())
                        if current_hash != source_hash and (not old or not old.get('created') or current_hash != old.get('sha256')):
                            raise ValueError(f'Existing companion file is not installer-owned: {name}')
                        created = bool(old.get('created')) if old else False
                        if current_hash != source_hash:
                            backup = backup_dir / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + name)
                            with backup.open('xb') as stream:
                                stream.write(runtime.read_bytes())
                            os.chmod(backup, 0o600)
                            backup_paths.append(backup)
                            _write_bytes(runtime, source_bytes, 0o600 if name == MODEL_POLICY else 0o700)
                            created = True
                    else:
                        _write_bytes(runtime, source_bytes, 0o600 if name == MODEL_POLICY else 0o700)
                        created = True
                    runtime_receipt[name] = {'sha256': source_hash, 'created': created}

            config_changed = changed != data
            if config_changed:
                if target.exists():
                    if read_config(target) != data:
                        raise ValueError('Hook configuration changed during install; retry after reviewing concurrent edits.')
                backup = _backup(target, backup_dir)
                backup_paths.append(backup)
                write_json(target, changed)
            else:
                backup = None
            if uninstall:
                # Remove only runtime files created by this installer and still byte-identical to its receipt.
                for name, owner in receipt.get('runtime', {}).items():
                    runtime = runtime_dir / name
                    if owner.get('created') and runtime.exists() and _sha256(runtime.read_bytes()) == owner.get('sha256'):
                        runtime.unlink()
                if receipt_path.exists():
                    receipt_path.unlink()
            else:
                new_receipt = {'version': 1, 'platform': platform,
                               'owned': {'event': EVENT, 'matcher': MATCHER, 'hook': expected_hook},
                               'runtime': runtime_receipt,
                               'original_had_hooks': receipt.get('original_had_hooks', 'hooks' in data),
                               'original_had_event': receipt.get('original_had_event', EVENT in hooks)}
                write_json(receipt_path, new_receipt)
            return {'action': 'uninstalled' if uninstall else 'installed', 'platform': platform,
                    'config': str(target), 'runtime': str(runtime_path), 'backup': str(backup) if backup else None}
        except Exception:
            for runtime, snapshot in runtime_snapshots.items():
                _restore(runtime, snapshot)
            _restore(target, config_snapshot)
            _restore(receipt_path, receipt_snapshot)
            # Keep preimage backups for recovery after a failed transaction.
            for directory in reversed(created_dirs):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform', choices=('codex', 'claude'), required=True)
    parser.add_argument('--core-dir', type=Path, required=True, help='Trusted installed legacy core directory.')
    parser.add_argument('--home', type=Path, default=Path.home(), help='Alternate home for fixtures.')
    parser.add_argument('--uninstall', action='store_true')
    parser.add_argument('--model-map', type=Path, help='Trusted Claude alias-to-native-model JSON policy.')
    args = parser.parse_args(argv)
    try:
        result = configure(args.home, args.platform, args.core_dir, args.uninstall, args.model_map)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
