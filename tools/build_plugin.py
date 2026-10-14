#!/usr/bin/env python3
"""Build a reproducible ZIP-format .plugin artifact using only Python stdlib."""
import argparse
import json
from pathlib import Path
import zipfile


def build(output: Path, *, learning_mcp=False, state_dir=None, policy_root=None) -> None:
    if learning_mcp and (state_dir is None or not state_dir.is_absolute()):
        raise ValueError('An absolute operator state-dir is required for an opt-in MCP plugin.')
    if policy_root is not None and not policy_root.is_absolute():
        raise ValueError('Operator policy-root must be absolute.')
    root = Path(__file__).resolve().parents[1] / 'claude-plugin/workflow-hooks-kit'
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        files = [(path.relative_to(root).as_posix(), path) for path in root.rglob('*') if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc']
        learning = root.parents[1] / 'learning'
        files.extend(('learning/' + name, learning / name) for name in ('cli.py', 'mcp_server.py', 'prompt_hook.py', 'README.md', 'MCP.md'))
        for name, path in sorted(files):
            if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        if learning_mcp:
            args = ['-B', '${CLAUDE_PLUGIN_ROOT}/learning/mcp_server.py', '--state-dir', str(state_dir)]
            if policy_root is not None:
                args += ['--policy-root', str(policy_root)]
            definition = {'mcpServers': {'workflow_learning': {'command': 'python3', 'args': args}}}
            info = zipfile.ZipInfo('.mcp.json', (2020, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, json.dumps(definition, indent=2) + '\n', compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('dist/workflow-hooks-kit.plugin'))
    parser.add_argument('--learning-mcp', action='store_true', help='Opt-in operator-local MCP plugin; do not publish configured private paths.')
    parser.add_argument('--state-dir', type=Path)
    parser.add_argument('--policy-root', type=Path)
    args = parser.parse_args()
    build(args.output, learning_mcp=args.learning_mcp, state_dir=args.state_dir, policy_root=args.policy_root)
