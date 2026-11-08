#!/usr/bin/env python3
"""Exercise skills CLI installation and a fresh Wencheng runtime, without model calls."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import signal
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
SKILLS_VERSION = '1.7.6'


def smoke(source: str, python: str, output: Path) -> dict:
    # A system temporary directory avoids accidental application discovery from
    # the source checkout's ancestors. Keep it for inspecting a failed install.
    work = Path(tempfile.mkdtemp(prefix='wencheng-skills-smoke-')).resolve()
    project = work / 'Agent project'
    unrelated = work / 'Unrelated directory'
    app = work / 'Application 中文 空格'
    project.mkdir()
    unrelated.mkdir()
    evidence = ROOT / 'test-output' / work.name
    evidence.mkdir(parents=True)
    checks = []
    report = dict(schema='wencheng.skills-install-smoke.v1',
                  started_at=datetime.now(timezone.utc).isoformat(),
                  source=source, skills_cli_version=SKILLS_VERSION,
                  telemetry_disabled=True, model_calls=False, checks=checks,
                  temporary_workspace=str(work), evidence=str(evidence.relative_to(ROOT)))
    process = None
    server_log = None
    env = dict(os.environ)
    for key in ('WENCHENG_ROOT', 'WENCHENG_DATA', 'PYTHONPATH', 'PYTHONHOME'):
        env.pop(key, None)
    env.update(PYTHONUTF8='1', DISABLE_TELEMETRY='1', DO_NOT_TRACK='1',
               npm_config_cache=str(ROOT / 'test-output/skills-npm-cache'),
               npm_config_update_notifier='false', NO_COLOR='1')

    def check(name, passed, **details):
        checks.append(dict(id=name, passed=bool(passed), **details))
        if not passed:
            raise AssertionError(name)

    def run(command, *, cwd=unrelated, log_name=None, timeout=60, parse=True):
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True,
                                text=True, encoding='utf-8', timeout=timeout)
        if log_name:
            (evidence / log_name).write_text(result.stdout + '\n' + result.stderr, encoding='utf-8')
        if result.returncode:
            raise RuntimeError(f'Command exited {result.returncode}: {command[0]} {command[1:3]}; '
                               f'see {log_name or "captured output"}: {result.stderr[-1500:]}')
        return json.loads(result.stdout) if parse else result.stdout

    try:
        npx = shutil.which('npx.cmd' if os.name == 'nt' else 'npx')
        if not npx:
            raise RuntimeError('npx was not found; install Node.js 22.20+ to exercise the skills CLI.')
        # Run npm's JS entry directly on Windows, so no shell reinterprets paths.
        if os.name == 'nt':
            npx_command = [str(Path(npx).parent / 'node.exe'),
                           str(Path(npx).parent / 'node_modules/npm/bin/npx-cli.js')]
        else:
            npx_command = [npx]
        run([*npx_command, '--yes', f'skills@{SKILLS_VERSION}', 'add', source,
             '--skill', 'wencheng', '--agent', 'codex', 'claude-code', '--copy', '--yes'],
            cwd=project, log_name='skills-install.log', timeout=180, parse=False)
        codex = project / '.agents/skills/wencheng'
        claude = project / '.claude/skills/wencheng'
        launcher = codex / 'scripts/wencheng.py'
        check('skills.project_scoped_codex_and_claude',
              (codex / 'SKILL.md').is_file() and (claude / 'SKILL.md').is_file()
              and launcher.is_file() and (claude / 'scripts/wencheng.py').is_file())
        check('skills.references_copied', all((folder / 'references/installation.md').is_file()
              and (folder / 'references/writing.md').is_file() for folder in (codex, claude)))
        report['installed_launcher_sha256'] = sha256(launcher.read_bytes()).hexdigest()
        source_path = Path(source)
        if source_path.exists():
            original = source_path / 'skills/wencheng/scripts/wencheng.py'
            check('skills.local_source_matches', original.read_bytes() == launcher.read_bytes())
        check('skills.no_source_checkout_ancestor', ROOT not in unrelated.parents
              and ROOT not in launcher.parents and not launcher.is_symlink())

        setup = run([python, str(launcher), 'setup', '--app-dir', str(app)],
                    log_name='setup.log', timeout=360)
        check('setup.downloaded_verified_runtime', setup['setup_complete'] and setup['downloaded']
              and Path(setup['application_root']) == app and setup['version'] == '0.1.0-rc.1')
        binding = json.loads((codex / 'wencheng-install.json').read_text('utf-8'))
        check('setup.binding_to_explicit_directory', Path(binding['application_root']) == app)
        manifest = json.loads((app / 'RELEASE-MANIFEST.json').read_text('utf-8'))
        check('setup.runtime_payload_hashes', all(
            sha256((app / item['path']).read_bytes()).hexdigest() == item['sha256']
            for item in manifest['files']))
        venv_python = app / ('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python')
        runtime = run([str(venv_python), '-c',
                       'import json,sys;print(json.dumps(dict(version=sys.version,prefix=sys.prefix,base=sys.base_prefix)))'])
        report['python_version'] = runtime['version']
        check('setup.isolated_virtual_environment', Path(runtime['prefix']).resolve() == app / '.venv'
              and runtime['prefix'] != runtime['base'])

        def cli(*arguments):
            return run([python, str(launcher), *arguments])

        check('workflow.initial_project_list_empty', cli('projects') == [])
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def request(path, payload=None, *, raw=False):
            data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
            req = urllib.request.Request(base + path, data=data,
                  headers={'Content-Type': 'application/json', 'Accept-Language': 'en'})
            with opener.open(req, timeout=15) as response:
                value = response.read()
            return value if raw else json.loads(value)

        server_log = (evidence / 'server.log').open('wb')
        options = dict(cwd=unrelated, env=env, stdin=subprocess.DEVNULL,
                       stdout=server_log, stderr=subprocess.STDOUT)
        if os.name == 'nt':
            options['creationflags'] = subprocess.CREATE_NO_WINDOW
        else:
            options['start_new_session'] = True
        # Launch the installed skill, not the source application's entry point.
        process = subprocess.Popen([python, str(launcher), 'start', '--port', str(port)], **options)
        deadline = time.monotonic() + 25
        while True:
            if process.poll() is not None:
                raise RuntimeError('Installed skill server exited; see server.log.')
            try:
                health = request('/api/health')
                break
            except urllib.error.URLError:
                if time.monotonic() > deadline:
                    raise TimeoutError('Installed application did not become healthy.')
                time.sleep(.2)
        check('http.health', health.get('ok') and health.get('app') == 'wencheng'
              and health.get('version') == '0.1.0-rc.1')
        check('http.prebuilt_frontend', request('/', raw=True) == (app / 'dist/index.html').read_bytes())
        assets = [entry['path'] for entry in manifest['files'] if entry['path'].startswith('dist/assets/')]
        check('http.prebuilt_assets', bool(assets) and all(
              request('/' + name.removeprefix('dist/'), raw=True) == (app / name).read_bytes()
              for name in assets))

        title = 'Skill installation / 安装验收'
        original = '需要强调的是，本研究使用相同的采样频率记录三个实验组的数据。'
        replacement = '本研究以相同的采样频率记录三个实验组的数据。'
        english = 'The method was evaluated on three datasets under the same sampling conditions.'
        created = cli('create', '--title', title, '--text', original)
        pid = created['id']
        cli('append', pid, '--text', english)
        view = request('/api/projects/' + pid)
        check('workflow.progressive_bilingual_drafting',
              [b['text'] for b in view['blocks']] == [title, original, english])
        selected = view['blocks'][1]
        marked = request(f'/api/projects/{pid}/annotations', dict(
            block_id=selected['id'], start=0, end=len(original), quote=original,
            instruction='删去空泛强调，保留采样条件和实验组数量。'))
        annotation = marked['annotations'][-1]
        tasks = cli('tasks', pid)
        check('workflow.exact_annotation_task', len(tasks['tasks']) == 1
              and tasks['tasks'][0]['id'] == annotation['id'] and tasks['tasks'][0]['quote'] == original)
        result_file = work / 'review-result.json'
        result_file.write_text(json.dumps(dict(project_id=pid, results=[dict(
            id=annotation['id'], quote=original, replacement=replacement,
            reason='Remove empty emphasis while retaining the factual content.')]), ensure_ascii=False), encoding='utf-8')
        cli('apply', pid, str(result_file))
        pending = request('/api/projects/' + pid)
        check('workflow.review_before_acceptance', pending['blocks'][1]['text'] == original
              and pending['annotations'][-1]['replacement'] == replacement)
        request(f'/api/projects/{pid}/annotations/{annotation["id"]}/apply', {})
        revised = request('/api/projects/' + pid)
        check('workflow.accepted_revision_visible', revised['blocks'][1]['text'] == replacement)
        exported = work / 'accepted-bilingual.docx'
        cli('export', pid, str(exported))
        docx = exported.read_bytes()
        check('workflow.export_bytes_match_http', docx == request(f'/api/projects/{pid}/export', raw=True))
        with ZipFile(exported) as archive:
            document = ET.fromstring(archive.read('word/document.xml'))
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        check('workflow.native_word_revisions', bool(document.findall('.//w:del', ns))
              and bool(document.findall('.//w:ins', ns))
              and '需要强调的是' in ''.join(t.text or '' for t in document.findall('.//w:delText', ns)))
        check('workflow.english_preserved', english in ''.join(t.text or '' for t in document.findall('.//w:t', ns)))
        report['export_sha256'] = sha256(docx).hexdigest()
        claude_launcher = claude / 'scripts/wencheng.py'
        rebound = run([python, str(claude_launcher), 'setup', '--bind', str(app)], log_name='claude-bind.log')
        claude_projects = run([python, str(claude_launcher), 'projects'])
        check('workflow.claude_copy_binds_same_application', rebound['bound_existing']
              and [p['id'] for p in claude_projects] == [pid])
        check('workflow.data_stays_in_installed_application',
              (app / '.wencheng/projects' / pid / 'current.docx').read_bytes() == docx)
        report['passed'] = True
    except Exception as error:
        report.update(passed=False, error=f'{type(error).__name__}: {error}')
        raise
    finally:
        if process is not None:
            # The launcher dispatches into the runtime's venv. Windows needs its
            # child tree stopped too; this PID was created only by this test.
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               capture_output=True, check=False)
            else:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass  # The server may have exited before cleanup.
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        if server_log:
            server_log.close()
        report['completed_at'] = datetime.now(timezone.utc).isoformat()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default=str(ROOT), help='Local checkout or owner/repo for a published skill.')
    parser.add_argument('--python', default=sys.executable, help='Python 3.11+ for a fresh runtime setup.')
    parser.add_argument('--output', type=Path, default=ROOT / 'test-output/skills-install-smoke.json')
    args = parser.parse_args()
    result = smoke(args.source, args.python, args.output.resolve())
    print(json.dumps(dict(passed=result['passed'], checks=len(result['checks']), report=str(args.output.resolve()))))
