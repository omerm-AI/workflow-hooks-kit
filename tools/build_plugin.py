#!/usr/bin/env python3
"""Build a reproducible ZIP-format .plugin artifact using only Python stdlib."""
import argparse
from pathlib import Path
import zipfile


def build(output: Path) -> None:
    root = Path(__file__).resolve().parents[1] / 'claude-plugin/workflow-hooks-kit'
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        files = [(path.relative_to(root).as_posix(), path) for path in root.rglob('*') if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc']
        learning = root.parents[1] / 'learning'
        files.extend(('learning/' + name, learning / name) for name in ('cli.py', 'README.md'))
        for name, path in sorted(files):
            if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('dist/workflow-hooks-kit.plugin'))
    build(parser.parse_args().output)
