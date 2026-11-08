"""PDF proof HTTP checks with real local PDFium rendering and no network."""
from hashlib import sha256
from io import BytesIO
import importlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import pypdfium2 as pdfium
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
api = importlib.import_module('backend.app')
from backend import proof, store


def pdf_bytes(sizes=((612, 792), (792, 612))):
    stream = BytesIO()
    with pdfium.PdfDocument.new() as document:
        for width, height in sizes:
            document.new_page(width, height).close()
        document.save(stream)
    return stream.getvalue()


class ProofTests(unittest.TestCase):
    def setUp(self):
        self.test_output = ROOT / 'test-output'
        self.test_output.mkdir(exist_ok=True)
        self.data = Path(tempfile.mkdtemp(prefix='proof-test-', dir=self.test_output)).resolve()
        self.data_patch = patch.object(store, 'DATA', self.data)
        self.data_patch.start()
        self.client = api.app.test_client()
        self.project = self.ok(self.client.post('/api/projects', json={
            'title': 'Proof test', 'paragraphs': ['Word report text.']}))
        self.pid = self.project['id']
        self.endpoint = f'/api/projects/{self.pid}/proof'
        self.original = store.document(self.pid)

    def tearDown(self):
        self.data_patch.stop()
        target = self.data.resolve()
        if target.parent != self.test_output.resolve() or not target.name.startswith('proof-test-'):
            raise AssertionError('Refusing cleanup outside this test directory')
        shutil.rmtree(target)

    def ok(self, response):
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def upload(self, data=None, filename='Word-proof.pdf'):
        return self.client.post(self.endpoint, data={
            'file': (BytesIO(data if data is not None else pdf_bytes()), filename)},
            content_type='multipart/form-data')

    def test_upload_page_dimensions_lazy_cache_and_immutable_docx(self):
        missing = self.ok(self.client.get(self.endpoint))
        self.assertFalse(missing['exists'])
        self.assertEqual(missing['pages'], [])
        self.assertEqual(missing['current_docx_sha256'], sha256(self.original).hexdigest())
        self.assertEqual(self.client.get(self.endpoint + '/pages/1').status_code, 404)
        data = pdf_bytes()
        meta = self.ok(self.upload(data, '../Word-proof.pdf'))
        self.assertTrue(meta['exists'])
        self.assertFalse(meta['stale'])
        self.assertEqual(meta['filename'], 'Word-proof.pdf')
        self.assertEqual(meta['docx_sha256'], missing['current_docx_sha256'])
        self.assertEqual(meta['pages'], [
            dict(number=1, width=1275, height=1651, width_pt=612, height_pt=792),
            dict(number=2, width=1651, height=1275, width_pt=792, height_pt=612)])
        directory = store.directory(self.pid) / 'proof'
        self.assertEqual(len(list(directory.glob('*.png'))), 0)
        self.assertEqual(next(directory.glob('*.pdf')).read_bytes(), data)
        response = self.client.get(self.endpoint + '/pages/2')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'image/png')
        self.assertEqual(response.headers['Cache-Control'], 'no-cache')
        with Image.open(BytesIO(response.data)) as image:
            self.assertEqual(image.size, (1651, 1275))
        with patch.object(proof, '_pdfium', side_effect=AssertionError('Cached image should not render again')):
            cached = self.client.get(self.endpoint + '/pages/2?v=repeat')
        self.assertEqual(cached.data, response.data)
        self.assertEqual(store.document(self.pid), self.original)
        self.assertEqual(store.load(self.pid)['version'], self.project['version'])

    def test_document_changes_stale_and_undo_restores_hash_match(self):
        self.ok(self.upload())
        project = self.ok(self.client.post(f'/api/projects/{self.pid}/annotations', json={
            'block_id': 'p1', 'start': 0, 'end': 4, 'quote': 'Word', 'instruction': 'Change Word to A'}))
        self.assertFalse(self.ok(self.client.get(self.endpoint))['stale'])
        aid = project['annotations'][-1]['id']
        self.ok(self.client.post(f'/api/projects/{self.pid}/tasks', json={
            'project_id': self.pid, 'results': [{'id': aid, 'quote': 'Word', 'replacement': 'A'}]}))
        self.ok(self.client.post(f'/api/projects/{self.pid}/annotations/{aid}/apply'))
        stale = self.ok(self.client.get(self.endpoint))
        self.assertTrue(stale['stale'])
        self.assertNotEqual(stale['docx_sha256'], stale['current_docx_sha256'])
        self.assertEqual(self.client.get(self.endpoint + '/pages/1').status_code, 200)
        self.ok(self.client.post(f'/api/projects/{self.pid}/undo'))
        restored = self.ok(self.client.get(self.endpoint))
        self.assertFalse(restored['stale'])
        self.assertEqual(restored['docx_sha256'], restored['current_docx_sha256'])

    def test_reupload_uses_new_cache_and_invalid_upload_keeps_old_proof(self):
        old = self.ok(self.upload(pdf_bytes(((612, 792),))))
        first = self.client.get(self.endpoint + '/pages/1').data
        for bad, name in [(b'not PDF', 'wrong.pdf'), (b'%PDF-broken', 'broken.pdf'),
                          (pdf_bytes(), 'not-a-pdf.docx')]:
            with self.subTest(name=name):
                self.assertEqual(self.upload(bad, name).status_code, 400)
                self.assertEqual(self.ok(self.client.get(self.endpoint)), old)
                self.assertEqual(self.client.get(self.endpoint + '/pages/1').data, first)
        new = self.ok(self.upload(pdf_bytes(((300, 400),))))
        self.assertNotEqual(new['created_at'], old['created_at'])
        self.assertEqual(new['docx_sha256'], old['docx_sha256'])
        directory = store.directory(self.pid) / 'proof'
        self.assertEqual(len(list(directory.glob('*.pdf'))), 1)
        self.assertEqual(len(list(directory.glob('*.png'))), 0)
        image_response = self.client.get(self.endpoint + '/pages/1')
        with Image.open(BytesIO(image_response.data)) as image:
            self.assertEqual(image.size, (625, 834))

    def test_size_page_count_and_page_dimensions_limits(self):
        with patch.object(proof, 'MAX_PDF_BYTES', 64):
            self.assertEqual(self.upload(b'%PDF-' + b'x' * 64).status_code, 400)
        with patch.object(proof, 'MAX_PAGES', 1):
            self.assertEqual(self.upload().status_code, 400)
        with patch.object(proof, 'MAX_PAGE_PIXELS', 100):
            self.assertEqual(self.upload().status_code, 400)
        self.assertFalse(self.ok(self.client.get(self.endpoint))['exists'])
        self.assertEqual(store.document(self.pid), self.original)

    def test_project_and_page_paths_are_validated(self):
        self.assertEqual(self.client.get('/api/projects/not-a-project/proof').status_code, 400)
        self.assertEqual(self.client.get('/api/projects/' + 'f' * 32 + '/proof').status_code, 404)
        self.ok(self.upload())
        for number in (0, 3, 9999):
            self.assertEqual(self.client.get(self.endpoint + f'/pages/{number}').status_code, 404)


if __name__ == '__main__':
    unittest.main()
