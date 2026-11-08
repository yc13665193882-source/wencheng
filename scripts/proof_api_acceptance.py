"""Audit uploaded PDF proofs over real HTTP without touching the browser.

The audit command is read-only. The lifecycle command creates its own test
project, uploads a synthetic PDF, appends via the existing CLI, then undoes via
HTTP. It never uploads a proof to an existing project.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen
import uuid

import pypdfium2 as pdfium
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
SCALE = 150 / 72


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return sha256(data).hexdigest()


class Client:
    def __init__(self, base):
        self.base = base.rstrip('/')
        self.steps = []

    def call(self, method, endpoint, payload=None, file=None, raw=False):
        headers, data = {}, None
        if file is not None:
            filename, content = file
            boundary = 'wencheng-' + uuid.uuid4().hex
            data = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                    'Content-Type: application/pdf\r\n\r\n').encode() + content + f'\r\n--{boundary}--\r\n'.encode()
            headers['Content-Type'] = 'multipart/form-data; boundary=' + boundary
        elif payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        started = time.perf_counter()
        with urlopen(Request(self.base + endpoint, data=data, headers=headers, method=method), timeout=180) as response:
            content = response.read()
            self.steps.append(dict(method=method, endpoint=endpoint, status=response.status,
                                   content_type=response.headers.get('Content-Type'),
                                   seconds=round(time.perf_counter() - started, 4)))
        return content if raw else json.loads(content)

    def snapshot(self, pid):
        project = self.call('GET', f'/api/projects/{pid}')
        data = self.call('GET', f'/api/projects/{pid}/export', raw=True)
        second = self.call('GET', f'/api/projects/{pid}')
        if project['version'] != second['version']:
            raise RuntimeError('Document changed while capturing the baseline.')
        return dict(project_id=pid, version=project['version'], docx_sha256=digest(data), docx_bytes=len(data))


def finish(report, client, output):
    report['http_steps'] = client.steps
    report['finished_at'] = now()
    report['passed'] = bool(report['checks']) and all(c['passed'] for c in report['checks']) and 'error' not in report
    report['summary'] = dict(passed=sum(c['passed'] for c in report['checks']), total=len(report['checks']),
                             failures=[c['id'] for c in report['checks'] if not c['passed']])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def audit(pid, pdf_path, baseline_path, output, base):
    client = Client(base)
    report = dict(schema='wencheng.proof-api-audit.v1', started_at=now(), project_id=pid,
                  original_pdf=str(pdf_path.resolve()), checks=[], pages=[],
                  method='Independent bundled PDFium rendering at 150 dpi; exact RGB pixel comparison against every HTTP PNG. No backend rendering functions imported.')

    def check(identifier, passed, **evidence):
        report['checks'].append(dict(id=identifier, passed=bool(passed), **evidence))

    try:
        baseline = json.loads(baseline_path.read_text('utf-8-sig'))
        report['upload_baseline'] = baseline
        if baseline['project_id'] != pid:
            raise ValueError('Baseline project id does not match requested project.')
        before = client.snapshot(pid)
        metadata = client.call('GET', f'/api/projects/{pid}/proof')
        report['proof_metadata'] = metadata
        report['after_upload'] = before
        check('upload.docx_hash_unchanged', before['docx_sha256'] == baseline['docx_sha256'])
        check('upload.project_version_unchanged', before['version'] == baseline['version'])
        check('proof.bound_to_current_docx', metadata['exists'] and not metadata['stale']
              and metadata['docx_sha256'] == metadata['current_docx_sha256'] == before['docx_sha256'])
        original = pdf_path.read_bytes()
        report['pdf_sha256'] = digest(original)
        with pdfium.PdfDocument(original) as document:
            count = len(document)
            report['pdf_pages'] = count
            check('proof.page_count', len(metadata['pages']) == count, expected=count, actual=len(metadata['pages']))
            for index in range(count):
                number = index + 1
                raw = client.call('GET', f'/api/projects/{pid}/proof/pages/{number}', raw=True)
                with Image.open(BytesIO(raw)) as supplied:
                    actual = supplied.convert('RGB')
                with closing(document[index]) as page:
                    points = page.get_size()
                    with closing(page.render(scale=SCALE, draw_annots=True)) as bitmap:
                        expected = bitmap.to_pil().convert('RGB')
                try:
                    same_size = actual.size == expected.size
                    row = dict(number=number, api_size=list(actual.size), independent_size=list(expected.size),
                               width_pt=points[0], height_pt=points[1], same_size=same_size, png_sha256=digest(raw))
                    if same_size:
                        with ImageChops.difference(actual, expected) as diff:
                            row['difference_bbox'] = diff.getbbox()
                            if row['difference_bbox'] is None:
                                row.update(changed_pixels=0, max_channel_difference=0)
                            else:
                                channels = diff.split()
                                maximum = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
                                row['changed_pixels'] = maximum.width * maximum.height - maximum.histogram()[0]
                                row['max_channel_difference'] = maximum.getextrema()[1]
                                maximum.close()
                                for channel in channels:
                                    channel.close()
                    else:
                        row.update(difference_bbox=None, changed_pixels=None, max_channel_difference=None)
                    row['pixel_identical'] = same_size and row['changed_pixels'] == 0
                    info = metadata['pages'][index] if index < len(metadata['pages']) else {}
                    row['metadata_matches'] = (info.get('number') == number
                        and (info.get('width'), info.get('height')) == expected.size
                        and all(abs(info.get(key, -1) - value) < 0.001 for key, value in zip(('width_pt', 'height_pt'), points)))
                    report['pages'].append(row)
                finally:
                    actual.close()
                    expected.close()
                if number % 10 == 0 or number == count:
                    print(f'{pid[:8]}: checked {number}/{count} PDF pages', flush=True)
        check('proof.all_page_pixels_identical', all(p['pixel_identical'] for p in report['pages']),
              compared_pages=len(report['pages']), mismatches=[p['number'] for p in report['pages'] if not p['pixel_identical']])
        check('proof.all_page_metadata_correct', all(p['metadata_matches'] for p in report['pages']))
        after = client.snapshot(pid)
        report['after_page_checks'] = after
        check('rendering.docx_hash_unchanged', after['docx_sha256'] == before['docx_sha256'])
        check('rendering.project_version_unchanged', after['version'] == before['version'])
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    return finish(report, client, output)


def lifecycle(output, base):
    client = Client(base)
    report = dict(schema='wencheng.proof-lifecycle.v1', started_at=now(), checks=[],
                  note='Separate synthetic test project. HTTP create/upload/status/export/undo; append uses the existing CLI because no HTTP append endpoint exists. No model called.')

    def check(identifier, passed, **evidence):
        report['checks'].append(dict(id=identifier, passed=bool(passed), **evidence))

    try:
        project = client.call('POST', '/api/projects', dict(title='PDF校样生命周期验收（测试）',
                              paragraphs=['此项目仅用于测试校样过期与撤销。']))
        pid = project['id']
        report['project_id'] = pid
        before = client.snapshot(pid)
        stream = BytesIO()
        with pdfium.PdfDocument.new() as document:
            document.new_page(612, 792).close()
            document.save(stream)
        proof = client.call('POST', f'/api/projects/{pid}/proof', file=('synthetic-lifecycle.pdf', stream.getvalue()))
        uploaded = client.snapshot(pid)
        check('upload.unchanged_document_and_version', uploaded == before)
        check('upload.current_proof', proof['exists'] and not proof['stale'] and proof['docx_sha256'] == before['docx_sha256'])
        command = [sys.executable, str(ROOT / 'scripts/wencheng.py'), 'append', pid, '--text', '为测试校样过期而追加的一段。']
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=60, check=True)
        report['append_command'] = command
        report['append_result'] = json.loads(result.stdout)
        appended = client.snapshot(pid)
        stale = client.call('GET', f'/api/projects/{pid}/proof')
        check('append.changed_document_and_version', appended['docx_sha256'] != before['docx_sha256'] and appended['version'] > before['version'])
        check('append.proof_stale', stale['stale'] and stale['docx_sha256'] == before['docx_sha256']
              and stale['current_docx_sha256'] == appended['docx_sha256'])
        client.call('POST', f'/api/projects/{pid}/undo', {})
        undone = client.snapshot(pid)
        restored = client.call('GET', f'/api/projects/{pid}/proof')
        check('undo.exact_document_bytes_restored', undone['docx_sha256'] == before['docx_sha256'])
        check('undo.proof_current_again', not restored['stale'] and restored['exists']
              and restored['docx_sha256'] == restored['current_docx_sha256'] == before['docx_sha256'])
        check('undo.version_advances', undone['version'] > appended['version'])
        report['snapshots'] = dict(before=before, uploaded=uploaded, appended=appended, undone=undone)
        report['proof_states'] = dict(uploaded=proof, appended=stale, undone=restored)
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    return finish(report, client, output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8765')
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('audit')
    command.add_argument('--project', required=True)
    command.add_argument('--pdf', type=Path, required=True)
    command.add_argument('--baseline', type=Path, required=True)
    command.add_argument('--output', type=Path, required=True)
    command = sub.add_parser('lifecycle')
    command.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = (audit(args.project, args.pdf, args.baseline, args.output, args.base) if args.command == 'audit'
              else lifecycle(args.output, args.base))
    print(json.dumps({key:result.get(key) for key in ('passed', 'summary', 'project_id', 'error')}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
