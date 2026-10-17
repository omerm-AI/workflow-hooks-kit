#!/usr/bin/env python3
"""Local, reversible workflow hook configuration. Python 3.9+, macOS/Linux."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import shlex
import shutil
import stat
import sys
import tempfile
import os

EVENTS = ('UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'Stop')
SOURCE = Path(__file__).resolve().parent / 'claude-plugin/workflow-hooks-kit'
MATCHER = 'Bash|apply_patch|Edit|Write|MultiEdit|NotebookEdit|Agent|spawn_agent'
LEGACY_MATCHERS = {'Bash|apply_patch|Edit|Write|MultiEdit|NotebookEdit'}
LEARNING = Path(__file__).resolve().parent / 'learning'
MAX_CONFIG = 4_000_000


def command(home: Path, platform: str) -> str:
    script = home / ('.codex' if platform == 'codex' else '.claude') / 'workflow-hooks-kit/bin/tool_scope_hook.py'
    return 'python3 -B ' + shlex.quote(str(script)) + (' --claude' if platform == 'claude' else '')


def entry(home: Path, platform: str, event: str) -> dict:
    hook = {'type': 'command', 'command': command(home, platform), 'timeout': 10}
    if platform == 'codex' and event == 'UserPromptSubmit':
        hook['additionalContextLimit'] = 300
    group = {'hooks': [hook]}
    if event in {'PreToolUse', 'PostToolUse'}:
        group['matcher'] = MATCHER
    return group


def safe_path(path: Path, directory: bool = False) -> None:
    if path.is_symlink():
        raise ValueError(f'Refusing redirected path: {path}')
    if path.exists() and (not path.is_dir() if directory else not path.is_file()):
        raise ValueError(f'Unexpected file type: {path}')


def bounded_json(path: Path, limit: int) -> dict:
    safe_path(path)
    if not path.exists():
        return {}
    if path.stat().st_size > limit:
        raise ValueError('JSON file exceeds bounded size.')
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError('JSON document must be an object.')
    return data


def read_config(path: Path) -> dict:
    data = bounded_json(path, MAX_CONFIG)
    if not isinstance(data.get('hooks', {}), dict):
        raise ValueError('Hooks must be a JSON object; no changes made.')
    for event, groups in data.get('hooks', {}).items():
        if not isinstance(groups, list) or any(not isinstance(g, dict) or not isinstance(g.get('hooks'), list) or any(not isinstance(h, dict) for h in g['hooks']) for g in groups):
            raise ValueError(f'Invalid hook groups for {event}; no changes made.')
    return data


def read_receipt(path: Path) -> dict:
    data = bounded_json(path, 64_000)
    owned = data.get('owned', {})
    if not isinstance(owned, dict) or any(event not in EVENTS or not isinstance(value, dict) or not isinstance(value.get('hook'), dict) or value.get('matcher') not in (None, MATCHER, *LEGACY_MATCHERS) for event, value in owned.items()):
        raise ValueError('Invalid installer ownership receipt.')
    return data


def write_json(path: Path, data: dict) -> None:
    safe_path(path)
    fd, tmp = tempfile.mkstemp(prefix='.workflow-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def preflight(base: Path, target: Path, kit: Path) -> None:
    # Inspect every existing owned descendant before any copy or config mutation.
    safe_path(base, True)
    safe_path(target)
    safe_path(base / '.workflow-hooks-kit-install.lock')
    safe_path(kit, True)
    for name in ('bin', 'backups'):
        safe_path(kit / name, True)
    for name in ('install-receipt.json', 'WORK_STANDARDS.md', 'LEARNING.md'):
        safe_path(kit / name)
    if kit.exists():
        for directory, names, files in os.walk(kit, followlinks=False):
            for name in names:
                safe_path(Path(directory) / name, True)
            for name in files:
                safe_path(Path(directory) / name)


@contextmanager
def installation_lock(base: Path):
    base.mkdir(parents=True, exist_ok=True)
    path = base / '.workflow-hooks-kit-install.lock'
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('Installer lock must be regular.')
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


MCP_NAME = 'workflow_learning'
MCP_START = '# BEGIN workflow-hooks-kit learning MCP\n'
MCP_END = '# END workflow-hooks-kit learning MCP\n'


def mcp_definition(kit, state_dir, policy_root=None):
    args = ['-B', str(kit / 'learning/mcp_server.py'), '--state-dir', str(state_dir)]
    if policy_root is not None:
        args += ['--policy-root', str(policy_root)]
    return {'command': sys.executable, 'args': args}


def mcp_plan(home, platform, kit, uninstall, state_dir, policy_root):
    """Prepare exact owned edits before hook activation; never claim existing entries."""
    target = home / ('.codex/config.toml' if platform == 'codex' else '.claude.json')
    receipt = kit / 'mcp-install-receipt.json'
    previous = bounded_json(receipt, 64_000)
    owner = previous.get('owned')
    if owner is not None and not isinstance(owner, (dict, str)):
        raise ValueError('Invalid MCP ownership receipt.')
    safe_path(target)
    before = target.read_bytes() if target.exists() else b''
    if len(before) > MAX_CONFIG:
        raise ValueError('MCP config exceeds bounded size.')
    definition = mcp_definition(kit, state_dir, policy_root)
    new_owner = None
    if platform == 'claude':
        data = bounded_json(target, MAX_CONFIG)
        changed = copy.deepcopy(data)
        servers = changed.get('mcpServers', {})
        if not isinstance(servers, dict):
            raise ValueError('mcpServers must be an object.')
        current = servers.get(MCP_NAME)
        if owner is not None and current == owner:
            servers.pop(MCP_NAME)
        elif owner is not None and not uninstall:
            raise ValueError('Owned MCP definition changed; preserved without replacement.')
        if not uninstall:
            if MCP_NAME in servers and servers[MCP_NAME] != definition:
                raise ValueError('Existing MCP name collision; preserved without replacement.')
            if MCP_NAME not in servers:
                servers[MCP_NAME] = definition
                new_owner = definition
        if servers:
            changed['mcpServers'] = servers
        elif not previous.get('original_had_servers', 'mcpServers' in data):
            changed.pop('mcpServers', None)
        after = (json.dumps(changed, indent=2, ensure_ascii=False) + '\n').encode() if changed != data else before
        original = previous.get('original_had_servers', 'mcpServers' in data)
    else:
        try:
            import tomllib
        except ImportError as exc:
            raise ValueError('Optional Codex MCP installation requires Python 3.11+ for safe TOML validation.') from exc
        text = before.decode('utf-8')
        data = tomllib.loads(text)
        current = data.get('mcp_servers', {}).get(MCP_NAME)
        if owner is not None:
            if not isinstance(owner, str) or not owner.lstrip('\n').startswith(MCP_START) or not owner.endswith(MCP_END):
                raise ValueError('Invalid MCP TOML ownership receipt.')
            if text.count(owner) == 1:
                text = text.replace(owner, '', 1)
                current = tomllib.loads(text).get('mcp_servers', {}).get(MCP_NAME)
            elif not uninstall:
                raise ValueError('Owned MCP definition changed; preserved without replacement.')
        if not uninstall:
            if current is not None:
                if current != definition:
                    raise ValueError('Existing MCP name collision; preserved without replacement.')
            else:
                block = MCP_START + '[mcp_servers.' + MCP_NAME + ']\n'
                block += 'command = ' + json.dumps(definition['command']) + '\n'
                block += 'args = ' + json.dumps(definition['args']) + '\n' + MCP_END
                # Own the separator too, so unchanged uninstall restores exact original bytes.
                new_owner = ('\n' if text and not text.endswith('\n') else '') + block
                text += new_owner
        after = text.encode()
        tomllib.loads(text)
        original = False
    return {'target': target, 'receipt': receipt, 'before': before, 'after': after,
            'owned': new_owner, 'original_had_servers': original}


def apply_mcp(plan, backup_dir, stamp):
    target = plan['target']
    safe_path(target)
    current = target.read_bytes() if target.exists() else b''
    if current != plan['before']:
        raise ValueError('MCP config changed during install; no MCP configuration replaced.')
    if plan['after'] != plan['before']:
        backup = backup_dir / (stamp + '-mcp-' + target.name)
        if target.exists():
            shutil.copy2(target, backup)
        else:
            write_json(backup, {'config_was_absent': True})
        fd, tmp = tempfile.mkstemp(prefix='.workflow-mcp-', dir=target.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(plan['after'])
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    write_json(plan['receipt'], {'owned': plan['owned'], 'original_had_servers': plan['original_had_servers']})


def operate(home: Path, platform: str, uninstall: bool = False, *, learning_mcp=False, state_dir=None, policy_root=None) -> dict:
    base = home / ('.codex' if platform == 'codex' else '.claude')
    target = base / ('hooks.json' if platform == 'codex' else 'settings.json')
    kit = base / 'workflow-hooks-kit'
    preflight(base, target, kit)
    with installation_lock(base):
        preflight(base, target, kit)
        state_dir = state_dir or home / '.local/share/workflow-hooks-kit/learning'
        if learning_mcp and not uninstall:
            for path in (state_dir, policy_root):
                if path is not None and not path.is_absolute():
                    raise ValueError('MCP state and policy paths must be absolute.')
            if policy_root is not None:
                safe_path(policy_root, True)
                if not policy_root.is_dir():
                    raise ValueError('Policy root must already exist.')
        plan = mcp_plan(home, platform, kit, uninstall, state_dir, policy_root) if learning_mcp or (uninstall and (kit / 'mcp-install-receipt.json').exists()) else None
        return _operate_locked(home, platform, uninstall, target, kit, plan)


def _operate_locked(home, platform, uninstall, target, kit, mcp=None):
    data = read_config(target)
    changed = copy.deepcopy(data)
    receipt = kit / 'install-receipt.json'
    previous = read_receipt(receipt)
    owned = previous.get('owned', {})
    original_had_hooks = previous.get('original_had_hooks', 'hooks' in data)
    original_empty_events = previous.get('original_empty_events', [key for key, value in data.get('hooks', {}).items() if value == []])
    hooks = changed.setdefault('hooks', {})
    new_owned = {}
    for event in EVENTS:
        expected = entry(home, platform, event)
        exact = expected['hooks'][0]
        current = hooks.get(event, [])
        owner = owned.get(event)
        if owner and (owner['hook'] != exact or owner.get('matcher') not in (expected.get('matcher'), *LEGACY_MATCHERS)):
            raise ValueError('Receipt does not describe this installer command and matcher.')
        groups = []
        removed = False
        for group in current:
            candidates = group['hooks']
            can_remove = owner and group.get('matcher') == owner.get('matcher')
            kept = [h for h in candidates if not (can_remove and h == owner['hook'])]
            removed = removed or kept != candidates
            if kept or kept == candidates:
                groups.append({**group, 'hooks': kept})
        if not uninstall:
            exists = any(exact == h and g.get('matcher') == expected.get('matcher') for g in groups for h in g['hooks'])
            if not exists:
                groups.append(expected)
                new_owned[event] = {'hook': exact, 'matcher': expected.get('matcher')}
        if groups:
            hooks[event] = groups
        elif event in original_empty_events:
            hooks[event] = []
        elif event in hooks and not removed:
            hooks[event] = current
        else:
            hooks.pop(event, None)
    if not hooks and not original_had_hooks:
        changed.pop('hooks', None)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    kit.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup_dir = kit / 'backups'
    backup_dir.mkdir(exist_ok=True, mode=0o700)
    backup = None
    # Stage all runtime material before making any configured hook active.
    if not uninstall:
        with tempfile.TemporaryDirectory(prefix='.staging-', dir=kit) as directory:
            staging = Path(directory)
            staged_bin = staging / 'bin'
            staged_bin.mkdir()
            for source in sorted((SOURCE / 'scripts').glob('*.py')):
                shutil.copy2(source, staged_bin / source.name)
            shutil.copy2(LEARNING / 'cli.py', staged_bin / 'learning_cli.py')
            shutil.copy2(LEARNING / 'README.md', staging / 'LEARNING.md')
            staged_learning = staging / 'learning'
            staged_learning.mkdir()
            for name in ('cli.py', 'mcp_server.py', 'prompt_hook.py', 'MCP.md'):
                shutil.copy2(LEARNING / name, staged_learning / name)
            staged_policy = staging / 'WORK_STANDARDS.md'
            shutil.copy2(SOURCE / 'skills/work-standards/SKILL.md', staged_policy)
            # Preserve previous bytes before any runtime replacement.
            runtime_backup = backup_dir / (stamp + '-runtime')
            runtime_backup.mkdir()
            binaries = kit / 'bin'
            binaries.mkdir(exist_ok=True)
            for source in sorted(staged_bin.iterdir()):
                existing = binaries / source.name
                if existing.exists() and existing.read_bytes() != source.read_bytes():
                    shutil.copy2(existing, runtime_backup / source.name)
                os.replace(source, existing)
            learning_runtime = kit / 'learning'
            learning_runtime.mkdir(exist_ok=True)
            for source in staged_learning.iterdir():
                existing = learning_runtime / source.name
                if existing.exists() and existing.read_bytes() != source.read_bytes():
                    (runtime_backup / 'learning').mkdir(exist_ok=True)
                    shutil.copy2(existing, runtime_backup / 'learning' / source.name)
                os.replace(source, existing)
            for name in ('WORK_STANDARDS.md', 'LEARNING.md'):
                staged = staging / name
                existing_policy = kit / name
                if existing_policy.exists() and existing_policy.read_bytes() != staged.read_bytes():
                    shutil.copy2(existing_policy, runtime_backup / name)
                os.replace(staged, existing_policy)
            if not any(runtime_backup.iterdir()):
                runtime_backup.rmdir()  # Empty generated temporary directory only.
    if changed != data:
        backup = backup_dir / (stamp + '-' + target.name)
        if target.exists():
            shutil.copy2(target, backup)
        else:
            write_json(backup, {'config_was_absent': True})
        # Advisory locking coordinates our installers; detect foreign edits too.
        if read_config(target) != data:
            raise ValueError('Config changed during install; retry after reviewing concurrent edits.')
        write_json(target, changed)
    if mcp is not None:
        apply_mcp(mcp, backup_dir, stamp)
    write_json(receipt, {'platform': platform, 'owned': new_owned, 'uninstalled': uninstall, 'original_had_hooks': original_had_hooks, 'original_empty_events': original_empty_events})
    return {'platform': platform, 'config': str(target), 'backup': str(backup) if backup else None,
            'action': 'uninstalled' if uninstall else 'installed', 'runtime_retained': uninstall, 'learning_mcp_configured': mcp is not None and not uninstall}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform', choices=('codex', 'claude', 'both'), required=True)
    parser.add_argument('--home', type=Path, default=Path.home(), help='Alternate home; does not activate hooks in your real account.')
    parser.add_argument('--uninstall', action='store_true')
    parser.add_argument('--learning-mcp', action='store_true', help='Opt in to a local stdio broker; native runtime coverage is pending.')
    parser.add_argument('--state-dir', type=Path, help='Absolute shared learning store; defaults under the selected home.')
    parser.add_argument('--policy-root', type=Path, help='Existing absolute operator policy directory; never bundled.')
    args = parser.parse_args()
    if sys.version_info < (3, 9) or sys.platform not in ('darwin', 'linux'):
        parser.error('Requires Python 3.9+ on macOS/Linux.')
    home = args.home.expanduser().resolve()
    completed = []
    try:
        for platform in ('codex', 'claude') if args.platform == 'both' else (args.platform,):
            result = operate(home, platform, args.uninstall, learning_mcp=args.learning_mcp, state_dir=args.state_dir, policy_root=args.policy_root)
            completed.append(platform)
            print(json.dumps(result))
    except (OSError, ValueError) as exc:
        print(json.dumps({'error': str(exc), 'completed_platforms': completed, 'cross_platform_atomic': False}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
