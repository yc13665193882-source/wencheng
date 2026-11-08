#!/usr/bin/env python
"""Resolve the application and dispatch to its single shared CLI implementation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


RELEASE_VERSION = '0.1.0-rc.1'
RELEASE_SHA256 = 'aa87454eacb9d080d2152f9bb2fb2ae9a07facb1f5ba361e21b7496aba27fe16'
RELEASE_URL = (
    'https://github.com/yc13665193882-source/wencheng/releases/download/'
    f'v{RELEASE_VERSION}/wencheng-{RELEASE_VERSION}.zip'
)


def default_application_root() -> Path:
    return Path.home() / '.wencheng' / f'app-{RELEASE_VERSION}'


def is_application(root: Path) -> bool:
    return (root / 'backend/docx_engine.py').is_file() and (root / 'scripts/wencheng.py').is_file()


def is_managed_release(root: Path) -> bool:
    try:
        manifest = json.loads((root / 'RELEASE-MANIFEST.json').read_text(encoding='utf-8'))
        return (is_application(root) and (root / 'dist/index.html').is_file()
                and manifest.get('schema') == 'wencheng.release.v1'
                and manifest.get('version') == RELEASE_VERSION)
    except (OSError, ValueError, AttributeError):
        return False


def bind_application(root: Path) -> None:
    config_path = Path(__file__).resolve().parents[1] / 'wencheng-install.json'
    temporary = config_path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps({
        'skill': 'wencheng', 'schema_version': 1, 'application_root': str(root),
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(config_path)


def download_release(destination: Path) -> None:
    request = urllib.request.Request(RELEASE_URL, headers={'User-Agent': 'wencheng-skill-setup'})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open('wb') as output:
        shutil.copyfileobj(response, output)
    actual = hashlib.sha256(destination.read_bytes()).hexdigest()
    if actual != RELEASE_SHA256:
        raise ValueError(f'Release SHA256 mismatch: expected {RELEASE_SHA256}, got {actual}.')


def unpack_release(archive: Path, staging: Path) -> Path:
    folder = f'wencheng-{RELEASE_VERSION}'
    with ZipFile(archive) as package:
        for entry in package.infolist():
            path = PurePosixPath(entry.filename)
            if (not path.parts or path.parts[0] != folder or path.is_absolute()
                    or '..' in path.parts or '\\' in entry.filename or ':' in entry.filename
                    or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('Release contains an unexpected archive path.')
        package.extractall(staging)
    root = staging / folder
    if not is_managed_release(root):
        raise ValueError('Release does not contain the expected application and prebuilt frontend.')
    return root


def setup(arguments: list[str]) -> dict:
    parser = argparse.ArgumentParser(description='Install or bind the local Wencheng application.')
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument('--app-dir', type=Path, help='Application directory; defaults to ~/.wencheng/app-0.1.0-rc.1.')
    destination.add_argument('--bind', type=Path, help='Bind an existing application without downloading or installing dependencies.')
    args = parser.parse_args(arguments)
    if sys.version_info < (3, 11):
        raise ValueError('Wencheng requires Python 3.11 or newer. / 文澄需要 Python 3.11 或更新版本。')
    root = (args.bind or args.app_dir or default_application_root()).expanduser().resolve()
    skill = Path(__file__).resolve().parents[1]
    if not args.bind and (root == skill or skill in root.parents or root in skill.parents):
        raise ValueError('Choose an application directory outside the installed skill and its ancestors.')
    downloaded = False
    if args.bind:
        if not is_application(root) or not (root / 'dist/index.html').is_file():
            raise ValueError('The binding must point to a Wencheng application with its prebuilt frontend.')
    else:
        if root.exists() and (not root.is_dir() or any(root.iterdir())) and not is_managed_release(root):
            raise ValueError('The application directory is not empty or is a different release; choose an empty directory or use --bind.')
        if not is_managed_release(root):
            root.parent.mkdir(parents=True, exist_ok=True)
            print(f'Downloading Wencheng {RELEASE_VERSION} / 正在下载文澄…', file=sys.stderr, flush=True)
            with tempfile.TemporaryDirectory(prefix='.wencheng-setup-', dir=root.parent) as temporary:
                work = Path(temporary)
                archive = work / 'runtime.zip'
                download_release(archive)
                extracted = unpack_release(archive, work / 'unpacked')
                if root.exists():
                    root.rmdir()  # An empty destination only; never remove an existing application.
                extracted.rename(root)
            downloaded = True
        subprocess.run([sys.executable, str(root / 'scripts/setup.py')], cwd=root,
                       stdout=sys.stderr, check=True)
    bind_application(root)
    return {'application_root': str(root), 'version': RELEASE_VERSION if is_managed_release(root) else None,
            'downloaded': downloaded, 'bound_existing': bool(args.bind),
            'skill_directory': str(skill), 'setup_complete': True}


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
            managed = default_application_root()
            if is_managed_release(managed):
                candidates.append(managed)
    for root in candidates:
        if is_application(root):
            return root
    raise FileNotFoundError(
        'Wencheng application not found. Run this launcher with setup to install the verified runtime, '
        'or setup --bind PATH to connect an existing application. Set WENCHENG_ROOT to the application directory '
        'containing backend and scripts, or run scripts/install_skill.py again with --update.'
    )


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == 'setup':
        try:
            print(json.dumps(setup(sys.argv[2:]), ensure_ascii=False, indent=2))
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            print(f'Setup failed / 安装失败: {exc}', file=sys.stderr)
            sys.exit(1)
        return
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
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
    main()
