#!/usr/bin/env python3
"""Copy the Wencheng skill to an explicitly chosen agent skill directory."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
CONFIG_NAME = 'wencheng-install.json'


def install_skill(target: Path, *, update: bool = False, application_root: Path = ROOT) -> Path:
    root = application_root.expanduser().resolve()
    source = root / 'skills' / 'wencheng'
    if not (root / 'backend' / 'docx_engine.py').is_file() or not (root / 'scripts' / 'wencheng.py').is_file():
        raise ValueError('Application root must contain backend/docx_engine.py and scripts/wencheng.py.')
    if not (source / 'SKILL.md').is_file():
        raise ValueError('The application does not contain skills/wencheng/SKILL.md.')
    target = target.expanduser().resolve()
    if target == source or source in target.parents or target in source.parents:
        raise ValueError('Choose an installation directory outside the source skill directory and its ancestors.')
    if target.exists():
        if not target.is_dir():
            raise ValueError('The installation target is not a directory.')
        if any(target.iterdir()):
            if not update:
                raise ValueError('The target is not empty. Use --update only for an existing Wencheng installation.')
            try:
                installed = json.loads((target / CONFIG_NAME).read_text(encoding='utf-8'))
            except (OSError, ValueError) as exc:
                raise ValueError('Refusing to update an unrecognized skill directory. Choose an empty target.') from exc
            if not isinstance(installed, dict) or installed.get('skill') != 'wencheng':
                raise ValueError('Refusing to update a directory not marked as a Wencheng installation.')
    files = [path for path in sorted(source.rglob('*')) if path.is_file()
             and '__pycache__' not in path.parts and path.suffix != '.pyc' and path.name != CONFIG_NAME]
    target.mkdir(parents=True, exist_ok=True)
    for path in files:
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    (target / CONFIG_NAME).write_text(json.dumps({
        'skill': 'wencheng',
        'schema_version': 1,
        'application_root': str(root),
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True, type=Path,
                        help='Exact destination skill directory, for example .agents/skills/wencheng.')
    parser.add_argument('--update', action='store_true',
                        help='Update a directory previously created by this installer; retain extra files.')
    args = parser.parse_args()
    try:
        target = install_skill(args.target, update=args.update)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Installation failed: {exc}\n')
    print(f'Installed Wencheng skill: {target}')
    print(f'Application: {ROOT}')
    print('Reload skills or start a new conversation in your agent to discover it.')


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
