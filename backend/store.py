"""Project persistence. The original DOCX is immutable; edits have undo snapshots."""
from __future__ import annotations
import json
import os
import re
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('WENCHENG_DATA', ROOT / '.wencheng')).resolve()
_locks: dict[str, threading.RLock] = {}
_guard = threading.Lock()
_local = threading.local()

def now():
    return datetime.now(timezone.utc).isoformat()

@contextmanager
def lock(pid):
    with _guard:
        thread_lock = _locks.setdefault(pid, threading.RLock())
    with thread_lock:
        depths = getattr(_local, 'depths', {})
        _local.depths = depths
        if depths.get(pid, 0):
            depths[pid] += 1
            try:
                yield
            finally:
                depths[pid] -= 1
            return
        with (directory(pid) / '.lock').open('a+b') as handle:
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            depths[pid] = 1
            try:
                yield
            finally:
                depths.pop(pid, None)
                handle.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

def directory(pid):
    if not re.fullmatch(r'[a-f0-9]{32}', pid):
        raise ValueError('项目编号无效')
    result = DATA / 'projects' / pid
    if not result.is_dir():
        raise FileNotFoundError('项目不存在')
    return result

def write_json(path, obj):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)

def load(pid):
    return json.loads((directory(pid) / 'project.json').read_text(encoding='utf-8'))

def document(pid):
    return (directory(pid) / 'current.docx').read_bytes()

def create(title, data):
    pid = uuid.uuid4().hex
    path = DATA / 'projects' / pid
    path.mkdir(parents=True)
    (path / 'history').mkdir()
    (path / 'original.docx').write_bytes(data)
    (path / 'current.docx').write_bytes(data)
    project = dict(id=pid, title=title or '未命名文档', version=1, created_at=now(), updated_at=now(),
                   annotations=[], history=[], settings={'rules':'', 'style_sample':'', 'language':'auto'})
    write_json(path / 'project.json', project)
    return project

def save(pid, project, label, data=None):
    """Caller owns project lock. Keep a full document + state undo checkpoint."""
    path = directory(pid)
    old = load(pid)
    sid = uuid.uuid4().hex
    (path / 'history' / f'{sid}.docx').write_bytes(document(pid))
    write_json(path / 'history' / f'{sid}.json', old)
    project['history'] = old['history'] + [dict(id=sid, label=label, at=now(), version=old['version'])]
    project['version'] = old['version'] + 1
    project['updated_at'] = now()
    if data is not None:
        tmp = path / 'current.tmp'
        tmp.write_bytes(data)
        tmp.replace(path / 'current.docx')
    write_json(path / 'project.json', project)
    return project

def undo(pid):
    with lock(pid):
        current = load(pid)
        if not current['history']:
            raise ValueError('没有可撤销的操作')
        path = directory(pid)
        sid = current['history'][-1]['id']
        old = json.loads((path / 'history' / f'{sid}.json').read_text(encoding='utf-8'))
        old['version'] = current['version'] + 1
        old['updated_at'] = now()
        (path / 'current.docx').write_bytes((path / 'history' / f'{sid}.docx').read_bytes())
        write_json(path / 'project.json', old)
        return old

def list_projects():
    path = DATA / 'projects'
    if not path.exists():
        return []
    items = []
    for p in path.glob('*/project.json'):
        item = json.loads(p.read_text(encoding='utf-8'))
        items.append({k:item[k] for k in ('id','title','updated_at')})
    return sorted(items, key=lambda i:i['updated_at'], reverse=True)

def config():
    path = DATA / 'providers.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(provider='codex', model='', base_url='https://api.openai.com/v1', api_key_env='OPENAI_API_KEY')

def save_config(value):
    DATA.mkdir(parents=True, exist_ok=True)
    write_json(DATA / 'providers.json', value)
