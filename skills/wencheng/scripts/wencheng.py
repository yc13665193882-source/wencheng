#!/usr/bin/env python
"""Resolve the application and dispatch to its single shared CLI implementation."""
from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path


def application_root() -> Path:
    configured = os.environ.get("WENCHENG_ROOT")
    if configured:
        candidates = [Path(configured).expanduser().resolve()]
    else:
        here = Path(__file__).resolve()
        config_path = here.parents[1] / 'wencheng-install.json'
        candidates = []
        if config_path.is_file():
            try:
                config = json.loads(config_path.read_text(encoding='utf-8'))
                configured_root = config['application_root']
                if not isinstance(configured_root, str) or not configured_root:
                    raise ValueError('application_root must be a nonempty path')
                candidates.append(Path(configured_root).expanduser().resolve())
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise FileNotFoundError(
                    'Invalid wencheng-install.json. Reinstall the skill or set WENCHENG_ROOT.'
                ) from exc
        else:
            if len(here.parents) > 3:
                candidates.append(here.parents[3])
            for directory in (Path.cwd(), *Path.cwd().parents):
                candidates.extend((directory, directory / "wencheng"))
    for root in candidates:
        if (root / "backend" / "docx_engine.py").is_file() and (root / "scripts" / "wencheng.py").is_file():
            return root
    raise FileNotFoundError(
        'Wencheng application not found. Set WENCHENG_ROOT to the application directory '
        'containing backend and scripts, or run scripts/install_skill.py again with --update.'
    )


def main() -> None:
    try:
        root = application_root()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    entry = root / 'scripts' / 'wencheng.py'
    environment_python = root / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if environment_python.is_file() and Path(sys.prefix).resolve() != (root / '.venv').resolve():
        sys.exit(subprocess.run([str(environment_python), str(entry), *sys.argv[1:]], check=False).returncode)
    sys.argv[0] = str(entry)
    runpy.run_path(str(entry), run_name="__main__")


if __name__ == '__main__':
    main()
