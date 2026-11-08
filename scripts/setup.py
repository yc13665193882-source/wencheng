#!/usr/bin/env python3
"""Install Wencheng's Python dependencies into a local, isolated environment."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.version_info < (3, 11):
        raise SystemExit('Wencheng requires Python 3.11 or newer. / 文澄需要 Python 3.11 或更新版本。')
    environment = ROOT / '.venv'
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if environment.exists() and not (environment / 'pyvenv.cfg').is_file():
        raise SystemExit('The .venv directory already exists but is not a Python environment; choose an empty application folder.')
    if not python.is_file():
        print('Creating .venv / 正在创建项目虚拟环境…', flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    subprocess.run([str(python), '-c', 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'], check=True)
    print('Installing Python dependencies / 正在安装 Python 依赖…', flush=True)
    subprocess.run([str(python), '-m', 'pip', '--disable-pip-version-check', 'install',
                    '-r', str(ROOT / 'requirements.txt'), '-c', str(ROOT / 'constraints.txt')], check=True, cwd=ROOT)
    subprocess.run([str(python), '-c', 'import flask, lxml, docx, pypdfium2, PIL'], check=True, cwd=ROOT)
    print('Setup complete. / 安装完成。')
    if (ROOT / 'dist/index.html').is_file():
        print('The frontend is included; Node.js is not required. / 已附带前端，无需 Node.js。')
    else:
        print('Source checkout: build the frontend with npm ci and npm run build first.')
    print(f'Start: "{python}" scripts/wencheng.py start --open')


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        main()
    except (OSError, subprocess.CalledProcessError) as error:
        print(f'Setup failed / 安装失败: {error}', file=sys.stderr)
        raise SystemExit(1)
