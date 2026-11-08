#!/usr/bin/env python3
"""Install and exercise a release ZIP in a new directory, without model calls."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def digest(data):
    return sha256(data).hexdigest()


def smoke(archive_path: Path, python: str, output: Path) -> dict:
    scratch = ROOT / 'test-output'
    scratch.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='release-smoke-', dir=scratch))
    checks = []
    report = dict(schema='wencheng.release-smoke.v1', started_at=datetime.now(timezone.utc).isoformat(),
                  archive=archive_path.name, archive_sha256=digest(archive_path.read_bytes()), checks=checks,
                  method='Fresh ZIP extraction and new venv; localhost HTTP plus shared CLI; no model requests.')

    def check(name, passed, **evidence):
        checks.append(dict(id=name, passed=bool(passed), **evidence))
        if not passed:
            raise AssertionError(name)

    process = None
    try:
        with ZipFile(archive_path) as archive:
            entries = archive.namelist()
            names = [PurePosixPath(name) for name in entries]
            check('zip.paths', bool(names) and all(not n.is_absolute() and '..' not in n.parts and '\\' not in str(n) for n in names)
                  and len({n.parts[0] for n in names}) == 1)
            archive.extractall(work)
        app = work / names[0].parts[0]
        manifest = json.loads((app / 'RELEASE-MANIFEST.json').read_text('utf-8'))
        report['version'] = manifest['version']
        check('zip.payload_hashes', all(digest((app / f['path']).read_bytes()) == f['sha256']
              and (app / f['path']).stat().st_size == f['bytes'] for f in manifest['files']))
        check('zip.no_personal_state', not (app / '.wencheng').exists() and not (app / 'node_modules').exists()
              and not (app / 'acceptance').exists() and not (app / '.venv').exists())
        env = dict(os.environ)
        for key in ('PYTHONPATH', 'PYTHONHOME', 'WENCHENG_ROOT'):
            env.pop(key, None)
        env['WENCHENG_DATA'] = str(app / '.wencheng')
        env['PYTHONUTF8'] = '1'
        with (work / 'setup.log').open('w', encoding='utf-8') as log:
            subprocess.run([python, str(app / 'scripts/setup.py')], cwd=app, env=env,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)
        venv_python = app / ('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python')
        runtime = subprocess.check_output([str(venv_python), '-c',
            'import json,sys;print(json.dumps({"version":sys.version,"prefix":sys.prefix,"base_prefix":sys.base_prefix}))'],
            env=env, cwd=app, text=True, encoding='utf-8')
        runtime = json.loads(runtime)
        check('install.isolated_environment', runtime['prefix'] != runtime['base_prefix']
              and Path(runtime['prefix']).resolve() == (app / '.venv').resolve())
        report['python_version'] = runtime['version']
        report['installed_packages'] = json.loads(subprocess.check_output(
            [str(venv_python), '-m', 'pip', 'list', '--format=json', '--disable-pip-version-check'],
            env=env, cwd=app, text=True, encoding='utf-8'))

        def cli(*arguments):
            result = subprocess.run([str(venv_python), str(app / 'scripts/wencheng.py'), *arguments],
                env=env, cwd=app, capture_output=True, text=True, encoding='utf-8', check=True, timeout=30)
            return json.loads(result.stdout)

        check('cli.empty_projects', cli('projects') == [])
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def get(path):
            with opener.open(url + path, timeout=10) as response:
                return response.read()

        with (work / 'server.log').open('wb') as log:
            options = dict(cwd=app, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            if os.name == 'nt':
                options['creationflags'] = subprocess.CREATE_NO_WINDOW
            process = subprocess.Popen([str(venv_python), str(app / 'scripts/wencheng.py'), 'start', '--port', str(port)], **options)
            deadline = time.monotonic() + 20
            while True:
                if process.poll() is not None:
                    raise RuntimeError('Extracted application exited; see server.log.')
                try:
                    health = json.loads(get('/api/health'))
                    break
                except urllib.error.URLError:
                    if time.monotonic() > deadline:
                        raise TimeoutError('Extracted application did not become healthy.')
                    time.sleep(.2)
            check('http.health', health.get('app') == 'wencheng' and health.get('ok') is True
                  and health.get('version') == manifest['version'], response=health)
            check('http.prebuilt_frontend', get('/') == (app / 'dist/index.html').read_bytes())
            assets = [entry['path'] for entry in manifest['files'] if entry['path'].startswith('dist/assets/')]
            check('http.all_prebuilt_assets', bool(assets) and all(get('/' + name.removeprefix('dist/')) == (app / name).read_bytes() for name in assets), count=len(assets))
            created = cli('create', '--title', 'Release smoke 验证', '--text', 'First paragraph 第一段。')
            pid = created['id']
            appended = cli('append', pid, '--text', 'Second paragraph 第二段。')
            view = json.loads(get('/api/projects/' + pid))
            expected = ['Release smoke 验证', 'First paragraph 第一段。', 'Second paragraph 第二段。']
            check('workflow.create_append_visible', appended['version'] == 2
                  and [block['text'] for block in view['blocks']] == expected)
            export_path = work / 'smoke.docx'
            cli('export', pid, str(export_path))
            data = export_path.read_bytes()
            check('workflow.export_matches_http_and_project', data == get('/api/projects/' + pid + '/export')
                  and data == (app / '.wencheng/projects' / pid / 'current.docx').read_bytes(), sha256=digest(data))
            with ZipFile(export_path) as document:
                root = ET.fromstring(document.read('word/document.xml'))
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            paragraphs = [''.join(t.text or '' for t in p.findall('.//w:t', ns)) for p in root.findall('.//w:p', ns)]
            check('workflow.docx_text', paragraphs == expected)
            check('workflow.state_is_local_to_extracted_copy', len(list((app / '.wencheng/projects').iterdir())) == 1)
            request = urllib.request.Request(url + '/api/projects/demo', data=b'{}',
                headers={'Content-Type': 'application/json'}, method='POST')
            with opener.open(request, timeout=10) as response:
                demo = json.load(response)
            demo_text = '\n'.join(block['text'] for block in demo['blocks'])
            check('workflow.bilingual_demo_without_test_fixtures', not (app / 'tests').exists()
                  and '需要强调的是' in demo_text and 'It is important to note' in demo_text
                  and (app / '.wencheng/projects' / demo['id'] / 'current.docx').is_file())
            installed_skill = work / 'isolated-agent-skills/wencheng'
            subprocess.run([python, str(app / 'scripts/install_skill.py'), '--target', str(installed_skill)],
                env=env, cwd=work, capture_output=True, text=True, encoding='utf-8', check=True, timeout=30)
            installed_projects = json.loads(subprocess.check_output(
                [python, str(installed_skill / 'scripts/wencheng.py'), 'projects'],
                env=env, cwd=work, text=True, encoding='utf-8', timeout=30))
            check('workflow.installed_skill_resolves_extracted_application',
                  {item['id'] for item in installed_projects} == {pid, demo['id']})
        report['passed'] = True
    except Exception as error:
        report['passed'] = False
        report['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        report['completed_at'] = datetime.now(timezone.utc).isoformat()
        report['local_evidence_directory'] = work.relative_to(ROOT).as_posix()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--python', default=sys.executable, help='Python 3.11+ used to create a brand-new venv.')
    parser.add_argument('--output', type=Path, default=ROOT / 'release/smoke.json')
    args = parser.parse_args()
    result = smoke(args.archive.resolve(), args.python, args.output.resolve())
    print(json.dumps(dict(passed=result['passed'], checks=len(result['checks']), report=str(args.output.resolve()))))
