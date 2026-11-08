"""Local PDF proofs bound to the exact DOCX bytes they were uploaded against."""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
from io import BytesIO
import json
import math
import re
import threading
import uuid

from . import store

MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_PAGES = 300
MAX_PAGE_PIXELS = 24_000_000
RENDER_SCALE = 150 / 72
# PDFium does not permit simultaneous calls from different threads.
_pdf_lock = threading.Lock()


def _pdfium():
    try:
        import pypdfium2
        from PIL import Image  # noqa: F401 - required by bitmap.to_pil()
    except ImportError as exc:
        raise RuntimeError('PDF 校样依赖未安装，请重新安装项目 requirements.txt 中的依赖。') from exc
    return pypdfium2


def _record(root):
    path = root / 'metadata.json'
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding='utf-8'))
    if not re.fullmatch(r'[a-f0-9]{32}', value.get('artifact_id', '')):
        raise ValueError('PDF 校样记录无效，请重新上传。')
    return value


def _metadata(record, current_hash):
    if record is None:
        return dict(exists=False, stale=False, pages=[], docx_sha256=None,
                    current_docx_sha256=current_hash, filename=None, created_at=None)
    return dict(exists=True, stale=record['docx_sha256'] != current_hash,
                pages=record['pages'], docx_sha256=record['docx_sha256'],
                current_docx_sha256=current_hash, filename=record['filename'],
                created_at=record['created_at'])


def status(pid):
    with store.lock(pid):
        root = store.directory(pid) / 'proof'
        return _metadata(_record(root), sha256(store.document(pid)).hexdigest())


def _inspect_pdf(data):
    pdfium = _pdfium()
    with _pdf_lock:
        try:
            document = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as exc:
            raise ValueError('无法读取 PDF 校样，请上传未加密且能正常打开的 PDF。') from exc
        with document:
            count = len(document)
            if count < 1 or count > MAX_PAGES:
                raise ValueError(f'PDF 校样需要包含 1 至 {MAX_PAGES} 页。')
            pages = []
            for index in range(count):
                try:
                    with closing(document[index]) as page:
                        width_pt, height_pt = page.get_size()
                except pdfium.PdfiumError as exc:
                    raise ValueError(f'PDF 第 {index + 1} 页无法读取。') from exc
                if not all(math.isfinite(v) and v > 0 for v in (width_pt, height_pt)):
                    raise ValueError(f'PDF 第 {index + 1} 页尺寸无效。')
                width, height = math.ceil(width_pt * RENDER_SCALE), math.ceil(height_pt * RENDER_SCALE)
                if width * height > MAX_PAGE_PIXELS:
                    raise ValueError(f'PDF 第 {index + 1} 页过大，请使用常规论文纸张尺寸。')
                pages.append(dict(number=index + 1, width=width, height=height,
                                  width_pt=width_pt, height_pt=height_pt))
            return pages


def upload(pid, data, filename):
    if not data or len(data) > MAX_PDF_BYTES:
        raise ValueError('PDF 校样不能为空，且不能超过 50 MB。')
    if not data.lstrip().startswith(b'%PDF-'):
        raise ValueError('文件不是有效 PDF 校样。')
    # The source document cannot change between binding its hash and committing
    # the proof. Uploading a proof changes neither DOCX bytes nor undo history.
    with store.lock(pid):
        current_hash = sha256(store.document(pid)).hexdigest()
        pages = _inspect_pdf(data)
        root = store.directory(pid) / 'proof'
        root.mkdir(exist_ok=True)
        old = _record(root)
        identifier = uuid.uuid4().hex
        pdf_path = root / f'{identifier}.pdf'
        record = dict(artifact_id=identifier, docx_sha256=current_hash, pages=pages,
                      filename=filename.replace('\\', '/').rsplit('/', 1)[-1][:200],
                      created_at=store.now())
        pdf_path.write_bytes(data)
        try:
            store.write_json(root / 'metadata.json', record)
        except Exception:
            pdf_path.unlink()
            raise
        # Only the previous proof's generated files are removed, inside this
        # known project directory. The incoming filename never becomes a path.
        if old:
            for path in root.glob(old['artifact_id'] + '.*'):
                if path.is_file():
                    path.unlink()
        return _metadata(record, current_hash)


def page_png(pid, number):
    with store.lock(pid):
        root = store.directory(pid) / 'proof'
        record = _record(root)
        if record is None:
            raise FileNotFoundError('尚未上传 PDF 校样。')
        if number < 1 or number > len(record['pages']):
            raise FileNotFoundError('PDF 校样页码不存在。')
        cache = root / f'{record["artifact_id"]}.{number}.png'
        if not cache.exists():
            pdfium = _pdfium()
            with _pdf_lock, pdfium.PdfDocument(root / f'{record["artifact_id"]}.pdf') as document:
                with closing(document[number - 1]) as page:
                    with closing(page.render(scale=RENDER_SCALE, draw_annots=True)) as bitmap:
                        with bitmap.to_pil() as image:
                            buffer = BytesIO()
                            image.save(buffer, format='PNG')
            temporary = cache.with_suffix('.tmp')
            temporary.write_bytes(buffer.getvalue())
            temporary.replace(cache)
        return cache.read_bytes()
