"""Loopback-only HTTP API for Wencheng's shared browser and agent workflows."""
from __future__ import annotations
import io
import json
import threading
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException
from . import store, docx_engine, ai, rules, proof, i18n

app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
# Validate GETs as well as mutations: a loopback listener alone does not reject
# a non-local Host header after browser DNS rebinding.
app.config['TRUSTED_HOSTS'] = ['127.0.0.1', 'localhost', '[::1]']
jobs = {}
jobs_lock = threading.Lock()

def response_language():
    return i18n.language(request.headers.get('Accept-Language'))


@app.after_request
def localize_response(response):
    locale = response_language()
    # send_file responses (DOCX/PDF/PNG/task downloads) are handled separately.
    # Never rewrite their bytes or disturb file streaming.
    if response.is_json and not response.direct_passthrough:
        value = response.get_json(silent=True)
        if value is not None:
            response.set_data(app.json.dumps(i18n.response_copy(value, locale)))
    response.headers['Content-Language'] = 'en' if locale == 'en' else 'zh-CN'
    response.vary.add('Accept-Language')
    return response

@app.before_request
def local_requests():
    # Browsers must originate from our local UI; CLI clients have no Origin.
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('Origin')
        if origin:
            parsed = urlparse(origin)
            own_port = urlparse(request.host_url).port or 80
            if parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.port not in (own_port, 5173):
                return jsonify(error='仅允许本地文澄页面修改项目'), 403

@app.errorhandler(Exception)
def errors(exc):
    if isinstance(exc, FileNotFoundError):
        return jsonify(error=str(exc)), 404
    if isinstance(exc, KeyError):
        field = str(exc.args[0]) if exc.args else ''
        return jsonify(error=f'缺少字段或字段无效：{field}'), 400
    if isinstance(exc, zipfile.BadZipFile):
        return jsonify(error='文件不是有效 DOCX 文档'), 400
    if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
        return jsonify(error='结果文件不是有效的 UTF-8 JSON，请检查文件格式。'), 400
    if isinstance(exc, ValueError):
        return jsonify(error=str(exc)), 400
    if isinstance(exc, HTTPException):
        return jsonify(error=i18n.http_error(exc.code, exc.description, 'zh')), exc.code
    app.logger.exception('Request failed')
    return jsonify(error='操作失败：' + str(exc)), 500

def body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValueError('需要 JSON 请求正文')
    return value

def view(pid):
    with store.lock(pid):
        project = store.load(pid)
        project.update(docx_engine.read_document(store.document(pid)))
        return project

def validate_docx(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(p.file_size for p in archive.infolist()) > 250 * 1024 * 1024:
            raise ValueError('DOCX 解压后过大，请使用小于 250 MB 的文档')
        if 'word/document.xml' not in archive.namelist():
            raise ValueError('文件不是有效 DOCX 文档')
    return docx_engine.read_document(data)

def active_job(pid):
    with jobs_lock:
        return any(j['project_id'] == pid and j['status'] == 'running' for j in jobs.values())

def annotation(project, aid):
    result = next((a for a in project['annotations'] if a['id'] == aid), None)
    if result is None:
        raise ValueError('标记不存在')
    return result

def range_fields(item):
    selected = {key: item[key] for key in ('block_id', 'start', 'end', 'quote')}
    if item.get('end_block_id') is not None:
        selected['end_block_id'] = item['end_block_id']
    return selected


def check_range(doc, block_id, start, end, quote, end_block_id=None):
    return docx_engine.selection_range(doc, block_id, start, end, quote, end_block_id=end_block_id)


def absolute_range(blocks, selected):
    """Count code points plus one separator per paragraph, matching exported quotes."""
    positions = {}
    cursor = 0
    for block in blocks:
        positions[block['id']] = cursor
        cursor += len(block['text']) + 1
    return (positions[selected['block_id']] + selected['start'],
            positions[selected.get('end_block_id') or selected['block_id']] + selected['end'])


def anchored_range(blocks, start, end):
    def point(offset):
        cursor = 0
        for block in blocks:
            if cursor <= offset <= cursor + len(block['text']):
                return block['id'], offset - cursor
            cursor += len(block['text']) + 1
        raise ValueError('选区位置已改变，请重新标记。')
    first, left = point(start)
    last, right = point(end)
    result = dict(block_id=first, start=left, end=right)
    if first != last:
        result['end_block_id'] = last
    return result


def relocate_annotations(annotations, applied, before, after):
    start, end = absolute_range(before['blocks'], applied)
    old_text = '\n'.join(block['text'] for block in before['blocks'])
    new_text = '\n'.join(block['text'] for block in after['blocks'])
    delta = len(new_text) - len(old_text)
    if old_text == new_text:
        return
    for other in annotations:
        if other['id'] == applied['id'] or other['status'] not in ('pending', 'suggested'):
            continue
        try:
            left, right = absolute_range(before['blocks'], other)
            if left < end and right > start:
                raise ValueError('此选区与已应用的修改重叠，请重新标记。')
            if left >= end:
                left, right = left + delta, right + delta
            moved = anchored_range(after['blocks'], left, right)
            # Verify the exact quote, including paragraph boundaries, before storing new anchors.
            docx_engine.selection_range(after, **moved, quote=other['quote'], check_protected=False)
            other.pop('end_block_id', None)
            other.update(moved)
        except (KeyError, ValueError):
            other['status'] = 'conflict'
            other['reason'] = '此选区与已应用的修改重叠或原文已改变，请重新标记。'
            i18n.mark_system_fields(other, 'reason')

def add_annotation(project, item):
    item = dict(item)
    item.update(id=uuid.uuid4().hex, status='pending', base_version=project['version'])
    if 'category' not in item:
        item['category'] = '用户标记'
        i18n.mark_system_fields(item, 'category')
    if item.get('rule_id'):
        i18n.mark_system_fields(item, 'category', 'reason', 'instruction')
    project['annotations'].append(item)
    return item

@app.get('/api/health')
def health():
    release_version = store.ROOT / 'VERSION'
    if release_version.is_file():
        version = release_version.read_text('utf-8').strip()
    else:
        version = json.loads((store.ROOT / 'package.json').read_text('utf-8'))['version']
    return jsonify(ok=True, app='wencheng', version=version)

@app.get('/api/projects')
def projects():
    return jsonify(projects=store.list_projects())

@app.post('/api/projects')
def new_project():
    data = body()
    paragraphs = data.get('paragraphs', [])
    if not isinstance(paragraphs, list) or not all(isinstance(p, str) for p in paragraphs):
        raise ValueError('paragraphs 必须是字符串数组')
    title = str(data.get('title') or i18n.message('未命名文档', response_language()))
    p = store.create(title[:200], docx_engine.create_document(title, paragraphs))
    return jsonify(view(p['id']))

@app.post('/api/projects/demo')
def demo():
    data = docx_engine.create_document('面向真实读者的技术写作', [
        '1 研究背景',
        '需要强调的是，我们将严格按照前文已经明确的规则开展分析。值得注意的是，本研究使用相同的采样频率记录三个实验组的数据。',
        '这不仅是一个技术问题，更是一个方法论问题。实验结果表明，滤波后的信噪比提高了 3.2 dB；在低照度条件下，该改善仍需进一步验证。',
        '2 Discussion',
        'It is important to note that the proposed method was evaluated on three datasets. As previously mentioned, we follow the requirements outlined above. The mean error decreased from 0.24 to 0.18 under the same sampling conditions.',
        'The improvement may depend on illumination. This limitation should be retained when simplifying the discussion.'
    ])
    p = store.create('双语写作示例', data)
    return jsonify(view(p['id']))

@app.post('/api/projects/import')
def import_docx():
    f = request.files.get('file')
    if not f or not (f.filename or '').lower().endswith('.docx'):
        raise ValueError('请选择 .docx 文件')
    data = f.read()
    validate_docx(data)
    p = store.create(Path(f.filename).stem[:200], data)
    return jsonify(view(p['id']))

@app.get('/api/projects/<pid>')
def project(pid):
    return jsonify(view(pid))

@app.patch('/api/projects/<pid>/settings')
def settings(pid):
    values = body()
    with store.lock(pid):
        p = store.load(pid)
        for key in ('rules', 'style_sample', 'language'):
            if key in values:
                p['settings'][key] = str(values[key])
        store.save(pid, p, '更新文风设置')
    return jsonify(view(pid))

@app.post('/api/projects/<pid>/annotations')
def mark(pid):
    value = body()
    with store.lock(pid):
        doc = docx_engine.read_document(store.document(pid))
        selected = range_fields(value)
        check_range(doc, **selected)
        p = store.load(pid)
        selected['instruction'] = str(value.get('instruction') or '克制地改善表达，保留原意与正式文风。')
        if not value.get('instruction'):
            i18n.mark_system_fields(selected, 'instruction')
        add_annotation(p, selected)
        store.save(pid, p, '添加修改标记')
    return jsonify(view(pid))

@app.post('/api/projects/<pid>/analyze')
def analyze(pid):
    with store.lock(pid):
        p = store.load(pid)
        doc = docx_engine.read_document(store.document(pid))
        existing = {(a['block_id'], a['start'], a['end'], a['quote']) for a in p['annotations']}
        found = rules.scan(doc['blocks'], p['settings'])
        count = 0
        for item in found:
            key = (item['block_id'], item['start'], item['end'], item['quote'])
            if key in existing:
                continue
            try:
                check_range(doc, item['block_id'], item['start'], item['end'], item['quote'])
            except ValueError:
                continue
            add_annotation(p, item)
            existing.add(key)
            count += 1
        if count:
            store.save(pid, p, f'标记 {count} 处表达问题')
    return jsonify(view(pid))

def apply_annotation(pid, aid):
    with store.lock(pid):
        p = store.load(pid)
        a = annotation(p, aid)
        if a['status'] != 'suggested' or not isinstance(a.get('replacement'), str):
            raise ValueError('该标记还没有可应用的改稿')
        doc = store.document(pid)
        before = docx_engine.read_document(doc)
        check_range(before, **range_fields(a))
        output = docx_engine.apply_edit(doc, a['block_id'], a['start'], a['end'], a['quote'], a['replacement'], end_block_id=a.get('end_block_id'))
        relocate_annotations(p['annotations'], a, before, docx_engine.read_document(output))
        a['status'] = 'applied'
        store.save(pid, p, '应用改稿为 Word 修订', output)

def suggest_annotation(pid, aid, config, ui_language='zh'):
    with store.lock(pid):
        p = store.load(pid)
        a = dict(annotation(p, aid))
        if a['status'] not in ('pending', 'suggested'):
            raise ValueError('此标记无法再次生成建议')
        doc = docx_engine.read_document(store.document(pid))
        selected = check_range(doc, **range_fields(a))
        settings = dict(p['settings'])
        settings['ui_language'] = ui_language
        context = selected['text']
    result = ai.rewrite(a['quote'], a['instruction'], context, settings, config,
                        allow_paragraphs=a.get('end_block_id', a['block_id']) != a['block_id'])
    if not isinstance(result.get('replacement'), str):
        raise ValueError('模型没有返回有效改稿')
    with store.lock(pid):
        p = store.load(pid)
        current = annotation(p, aid)
        if current['status'] not in ('pending', 'suggested') or current['quote'] != a['quote']:
            raise ValueError('生成期间标记已改变，未写入旧建议')
        check_range(docx_engine.read_document(store.document(pid)), **range_fields(current))
        current.update(replacement=result['replacement'].replace('\r\n', '\n').replace('\r', '\n'),
                       reason=str(result.get('reason','')), status='suggested')
        i18n.mark_external_field(current, 'reason')
        store.save(pid, p, '生成局部改写建议')

@app.post('/api/projects/<pid>/annotations/<aid>/<action>')
def update_annotation(pid, aid, action):
    if action == 'suggest':
        suggest_annotation(pid, aid, store.config(), ui_language=response_language())
    elif action == 'apply':
        apply_annotation(pid, aid)
    elif action in ('reject', 'comment'):
        with store.lock(pid):
            p = store.load(pid)
            a = annotation(p, aid)
            output = None
            if action == 'reject':
                if a['status'] == 'applied':
                    raise ValueError('已应用的修改请通过历史撤销')
                a['status'] = 'rejected'
            else:
                if a.get('commented'):
                    raise ValueError('该标记已经写入 Word 批注')
                output = docx_engine.add_comment(store.document(pid), a['block_id'], a['start'], a['end'], a['quote'], a['instruction'], end_block_id=a.get('end_block_id'))
                a['commented'] = True
            store.save(pid, p, '拒绝建议' if action == 'reject' else '写入 Word 批注', output)
    else:
        raise ValueError('未知标记操作')
    return jsonify(view(pid))

@app.post('/api/projects/<pid>/undo')
def undo(pid):
    if active_job(pid):
        raise ValueError('请等待当前 AI 任务结束后撤销')
    store.undo(pid)
    return jsonify(view(pid))

@app.get('/api/projects/<pid>/export')
def export(pid):
    with store.lock(pid):
        p = store.load(pid)
        return send_file(io.BytesIO(store.document(pid)), mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document', as_attachment=True, download_name=p['title']+'.docx')

@app.get('/api/projects/<pid>/proof')
def proof_status(pid):
    response = jsonify(proof.status(pid))
    response.headers['Cache-Control'] = 'no-cache'
    return response

@app.post('/api/projects/<pid>/proof')
def upload_proof(pid):
    # Allow multipart framing in addition to the 50 MB file limit.
    request.max_content_length = proof.MAX_PDF_BYTES + 1024 * 1024
    file = request.files.get('file')
    if not file or not (file.filename or '').lower().endswith('.pdf'):
        raise ValueError('请选择本机 Word 导出的 .pdf 校样文件。')
    data = file.read(proof.MAX_PDF_BYTES + 1)
    return jsonify(proof.upload(pid, data, file.filename))

@app.get('/api/projects/<pid>/proof/pages/<int:number>')
def proof_page(pid, number):
    response = send_file(io.BytesIO(proof.page_png(pid, number)), mimetype='image/png')
    response.headers['Cache-Control'] = 'no-cache'
    return response

def task_payload(pid):
    p = view(pid)
    return dict(schema='wencheng.tasks.v1', project_id=pid, version=p['version'], title=p['title'], settings=p['settings'],
                instructions=i18n.TASK_INSTRUCTIONS,
                tasks=[dict(a, context=docx_engine.selection_range(p, **range_fields(a), check_protected=False)['text'])
                       for a in p['annotations'] if a['status']=='pending'])

@app.get('/api/projects/<pid>/tasks')
def tasks(pid):
    content = json.dumps(i18n.response_copy(task_payload(pid), response_language()), ensure_ascii=False, indent=2).encode('utf-8')
    return send_file(io.BytesIO(content), mimetype='application/json', as_attachment=True, download_name='wencheng-tasks.json')

def import_results(pid, results):
    if results.get('project_id') != pid or not isinstance(results.get('results'), list):
        raise ValueError('结果文件项目编号不匹配，或缺少 results 数组')
    with store.lock(pid):
        p = store.load(pid)
        doc = docx_engine.read_document(store.document(pid))
        for item in results['results']:
            a = annotation(p, item['id'])
            if a['status'] not in ('pending','suggested') or a['quote'] != item.get('quote'):
                raise ValueError('标记或原文已改变，不能导入旧结果')
            check_range(doc, **range_fields(a))
            if not isinstance(item.get('replacement'), str):
                raise ValueError('改稿必须是字符串')
            a.update(replacement=item['replacement'].replace('\r\n', '\n').replace('\r', '\n'),
                     reason=str(item.get('reason','')), status='suggested')
            i18n.mark_external_field(a, 'reason')
        store.save(pid, p, '导入聊天生成的改稿')

@app.post('/api/projects/<pid>/tasks')
def receive_tasks(pid):
    f = request.files.get('file')
    values = json.loads(f.read().decode('utf-8-sig')) if f else body()
    import_results(pid, values)
    return jsonify(view(pid))

@app.get('/api/providers')
def providers():
    config = store.config()
    return jsonify(providers=ai.providers_status(config), config=config)

@app.put('/api/providers')
def provider_settings():
    values = body()
    if values.get('provider') not in ('codex','claude','openai'):
        raise ValueError('请选择有效的 AI 接入方式')
    config = {k:str(values.get(k,'')) for k in ('provider','model','base_url','api_key_env')}
    store.save_config(config)
    return jsonify(providers=ai.providers_status(config), config=config)

def launch_job(pid, work):
    store.directory(pid)
    jid = uuid.uuid4().hex
    with jobs_lock:
        if any(j['project_id'] == pid and j['status'] == 'running' for j in jobs.values()):
            raise ValueError('此文档已有 AI 任务正在运行')
        jobs[jid] = dict(id=jid, project_id=pid, status='running', progress=0, error=None)
    def run():
        try:
            work(jobs[jid])
            jobs[jid]['status'] = 'done'
        except Exception as exc:
            jobs[jid].update(status='error', error=str(exc))
    threading.Thread(target=run, daemon=True, name=f'wencheng-{jid[:8]}').start()
    return jsonify(job_id=jid)

@app.post('/api/projects/<pid>/generate')
def generate(pid):
    values = body()
    prompt = str(values.get('prompt','')).strip()
    if not prompt:
        raise ValueError('请输入文档要求或提纲')
    config = store.config()
    settings = store.load(pid)['settings']
    settings['ui_language'] = response_language()
    def work(job):
        for paragraph in ai.generate(prompt, settings, config):
            if not paragraph.strip():
                continue
            with store.lock(pid):
                p = store.load(pid)
                data = docx_engine.append_paragraph(store.document(pid), paragraph)
                store.save(pid, p, '写入 AI 生成段落', data)
            job['progress'] += 1
    return launch_job(pid, work)

@app.post('/api/projects/<pid>/rewrite')
def rewrite_job(pid):
    values = body()
    p = store.load(pid)
    ids = values.get('annotation_ids') or [a['id'] for a in p['annotations'] if a['status']=='pending']
    if not ids:
        raise ValueError('请先添加修改标记或检查表达')
    config = store.config()
    locale = response_language()
    def work(job):
        for aid in ids:
            suggest_annotation(pid, aid, config, ui_language=locale)
            job['progress'] += 1
    return launch_job(pid, work)

@app.get('/api/jobs/<jid>')
def job_status(jid):
    if jid not in jobs:
        raise FileNotFoundError('任务不存在，服务可能已重启')
    return jsonify(jobs[jid])

@app.get('/')
@app.get('/<path:filename>')
def frontend(filename='index.html'):
    root = store.ROOT / 'dist'
    if not (root / 'index.html').exists():
        return i18n.message('前端尚未构建，请在项目目录运行 npm run build。', response_language()), 503
    return send_from_directory(root, filename if (root / filename).is_file() else 'index.html')
