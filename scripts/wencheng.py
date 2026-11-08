#!/usr/bin/env python
"""Shared CLI entry point for the local UI and Codex/Claude skills."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def service_running(url):
    """Probe localhost directly; only a refused connection means it needs starting."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        # Windows can take about two seconds to report a closed loopback port.
        with opener.open(url + '/api/health', timeout=4) as response:
            running = json.load(response)
    except urllib.error.HTTPError as exc:
        raise ValueError(f'{url} 已被其他服务占用（HTTP {exc.code}）') from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ConnectionRefusedError):
            return False
        raise ValueError(f'无法访问 {url}：{exc.reason}') from exc
    except (OSError, ValueError) as exc:
        raise ValueError(f'无法确认 {url} 的文澄服务：{exc}') from exc
    if not isinstance(running, dict) or running.get('app') != 'wencheng' or running.get('ok') is not True:
        raise ValueError(f'{url} 已被其他服务占用，请指定其他端口')
    return True


def ensure_service(port):
    from backend import store
    url = f'http://127.0.0.1:{port}'
    if service_running(url):
        return url
    store.DATA.mkdir(parents=True, exist_ok=True)
    log_path = store.DATA / f'server-{port}.log'
    options = dict(cwd=ROOT, stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NO_WINDOW
    else:
        options['start_new_session'] = True
    with log_path.open('ab') as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), 'start', '--port', str(port)],
            stdout=log, **options,
        )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if service_running(url):
            return url
        if process.poll() is not None:
            raise ValueError(f'文澄启动失败，请查看日志：{log_path}')
        time.sleep(.2)
    process.terminate()
    raise ValueError(f'等待文澄启动超时，请查看日志：{log_path}')


def open_project(project_id, port):
    from backend import store
    store.load(project_id)
    url = ensure_service(port) + '/?project=' + project_id
    try:
        opened = bool(webbrowser.open(url))
    except (OSError, webbrowser.Error):
        opened = False
    return {'project_id': project_id, 'url': url, 'browser_opened': opened}


def main():
    parser = argparse.ArgumentParser(description='文澄 — 本地双语 DOCX 审阅工作台')
    sub = parser.add_subparsers(dest='command', required=True)
    start = sub.add_parser('start', help='启动本地浏览器编辑器')
    start.add_argument('--port', type=int, default=8765)
    start.add_argument('--open', action='store_true')
    open_cmd = sub.add_parser('open', help='启动或复用服务，并打开指定文档的审阅页面')
    open_cmd.add_argument('project_id')
    open_cmd.add_argument('--port', type=int, default=8765)
    sub.add_parser('projects', help='列出本地项目')
    imp = sub.add_parser('import', help='将 DOCX 复制到本地项目')
    imp.add_argument('file', type=Path)
    create = sub.add_parser('create', help='创建一个 DOCX 项目')
    create.add_argument('--title', required=True)
    create.add_argument('--text', default='')
    append = sub.add_parser('append', help='追加一段正文，浏览器轮询可见')
    append.add_argument('project_id')
    append.add_argument('--text', required=True)
    for name in ('tasks', 'inspect', 'analyze', 'undo'):
        cmd = sub.add_parser(name)
        cmd.add_argument('project_id')
    tasks = sub.choices['tasks']
    tasks.add_argument('--output', type=Path)
    apply = sub.add_parser('apply', help='导入聊天生成的建议；默认仍需界面确认')
    apply.add_argument('project_id')
    apply.add_argument('file', type=Path)
    apply.add_argument('--accept', action='store_true', help='明确确认：把本批建议写为 Word 修订')
    export = sub.add_parser('export')
    export.add_argument('project_id')
    export.add_argument('file', type=Path)
    args = parser.parse_args()
    from backend import store, docx_engine
    if args.command == 'start':
        from backend.app import app
        if not (ROOT / 'dist' / 'index.html').exists():
            parser.error('请先在项目目录执行 npm install 和 npm run build')
        url = f'http://127.0.0.1:{args.port}'
        if service_running(url):
            print(f'文澄已在运行：{url}', flush=True)
            if args.open:
                webbrowser.open(url)
            return
        print(f'文澄已启动：{url}', flush=True)
        if args.open:
            import threading
            threading.Timer(1, lambda:webbrowser.open(url)).start()
        app.run(host='127.0.0.1', port=args.port, threaded=True, debug=False, use_reloader=False)
    elif args.command == 'open':
        output(open_project(args.project_id, args.port))
    elif args.command == 'projects':
        output(store.list_projects())
    elif args.command == 'import':
        from backend.app import validate_docx
        data = args.file.read_bytes()
        validate_docx(data)
        output(store.create(args.file.stem, data))
    elif args.command == 'create':
        output(store.create(args.title, docx_engine.create_document(args.title, [args.text] if args.text else [])))
    elif args.command == 'append':
        with store.lock(args.project_id):
            p = store.load(args.project_id)
            data = docx_engine.append_paragraph(store.document(args.project_id), args.text)
            output(store.save(args.project_id, p, '聊天写入新段落', data))
    elif args.command == 'tasks':
        from backend.app import task_payload
        value = task_payload(args.project_id)
        if args.output:
            args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
            output({'file':str(args.output.resolve()), 'tasks':len(value['tasks'])})
        else:
            output(value)
    elif args.command == 'inspect':
        from backend.app import view
        output(view(args.project_id))
    elif args.command == 'analyze':
        from backend.app import app
        with app.test_client() as client:
            response = client.post(f'/api/projects/{args.project_id}/analyze', json={})
            if response.status_code != 200:
                raise ValueError(response.json['error'])
            output(response.json)
    elif args.command == 'apply':
        from backend.app import import_results, apply_annotation
        result = json.loads(args.file.read_text(encoding='utf-8-sig'))
        import_results(args.project_id, result)
        if args.accept:
            for entry in result['results']:
                apply_annotation(args.project_id, entry['id'])
        output({'project_id':args.project_id, 'imported':len(result['results']), 'applied':args.accept})
    elif args.command == 'undo':
        output(store.undo(args.project_id))
    elif args.command == 'export':
        args.file.write_bytes(store.document(args.project_id))
        output({'file':str(args.file.resolve())})

if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        main()
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
