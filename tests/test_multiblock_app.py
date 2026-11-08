"""Cross-paragraph annotations use the same HTTP/CLI workflow as single ranges."""
from __future__ import annotations

import importlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from lxml import etree

from backend import docx_engine, store

api = importlib.import_module('backend.app')


class MultiblockAppTests(unittest.TestCase):
    def setUp(self):
        output = Path(__file__).resolve().parents[1] / 'test-output'
        output.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix='wencheng-multiblock-', dir=output)
        self.data_patch = patch.object(store, 'DATA', Path(self.directory.name))
        self.data_patch.start()
        self.client = api.app.test_client()

    def tearDown(self):
        self.data_patch.stop()
        self.directory.cleanup()

    def ok(self, response):
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def create(self, paragraphs):
        return self.ok(self.client.post('/api/projects', json={'title': '跨段测试', 'paragraphs': paragraphs}))

    def mark(self, project, block_id, start, end, end_block_id=None):
        blocks = project['blocks']
        first = next(i for i, b in enumerate(blocks) if b['id'] == block_id)
        last = next(i for i, b in enumerate(blocks) if b['id'] == (end_block_id or block_id))
        text = '\n'.join(b['text'][start if i == first else 0:end if i == last else len(b['text'])]
                         for i, b in enumerate(blocks) if first <= i <= last)
        payload = dict(block_id=block_id, start=start, end=end, quote=text, instruction='整体调整衔接与重复，可以重新分段')
        if end_block_id:
            payload['end_block_id'] = end_block_id
        result = self.ok(self.client.post(f"/api/projects/{project['id']}/annotations", json=payload))
        return result, result['annotations'][-1]

    def supply(self, project, annotation, replacement):
        return self.ok(self.client.post(f"/api/projects/{project['id']}/tasks", json={
            'project_id': project['id'], 'results': [{'id': annotation['id'], 'quote': annotation['quote'],
                                                     'replacement': replacement, 'reason': '整体修订'}]}))

    def action(self, project, annotation, action):
        return self.ok(self.client.post(f"/api/projects/{project['id']}/annotations/{annotation['id']}/{action}"))

    def test_cross_paragraph_mark_exports_one_task_with_all_context(self):
        project = self.create(['前缀第一段', '中间第二段', '第三段后缀'])
        project, annotation = self.mark(project, 'p1', 2, 3, 'p3')
        self.assertEqual(annotation['end_block_id'], 'p3')
        self.assertEqual(annotation['quote'], '第一段\n中间第二段\n第三段')
        tasks = json.loads(self.client.get(f"/api/projects/{project['id']}/tasks").data)
        self.assertEqual(len(tasks['tasks']), 1)
        self.assertEqual(tasks['tasks'][0]['context'], '前缀第一段\n中间第二段\n第三段后缀')
        self.assertEqual(tasks['tasks'][0]['end_block_id'], 'p3')

    def test_sidebar_uses_one_whole_range_and_allows_new_paragraphs(self):
        project = self.create(['首段重复背景', '次段重复背景', '末段结论'])
        project, annotation = self.mark(project, 'p1', 0, 4, 'p3')
        with patch.object(api.ai, '_chunks', return_value=iter([json.dumps({
                'replacement': '整理后的背景\n衔接后的结论', 'reason': '统整三段'}, ensure_ascii=False)])) as model:
            project = self.action(project, annotation, 'suggest')
        self.assertEqual(model.call_count, 1)
        prompt = model.call_args.args[0]
        self.assertIn('跨段整体选区', prompt)
        self.assertIn('首段重复背景\\n次段重复背景\\n末段结论', prompt)
        self.assertEqual(project['annotations'][0]['replacement'], '整理后的背景\n衔接后的结论')
        self.assertEqual(project['annotations'][0]['status'], 'suggested')
        self.assertEqual([b['text'] for b in project['blocks'][1:]], ['首段重复背景', '次段重复背景', '末段结论'])

    def test_import_apply_export_and_undo_preserve_partial_endpoints(self):
        project = self.create(['前缀第一段', '中间第二段', '第三段后缀', '尾随段落'])
        initial = store.document(project['id'])
        project, annotation = self.mark(project, 'p1', 2, 3, 'p3')
        project = self.supply(project, annotation, '新甲\n新乙')
        project = self.action(project, annotation, 'apply')
        self.assertEqual([b['text'] for b in project['blocks']], ['跨段测试', '前缀新甲', '新乙后缀', '尾随段落'])
        self.assertEqual(project['annotations'][0]['status'], 'applied')
        exported = self.client.get(f"/api/projects/{project['id']}/export")
        self.assertEqual(exported.status_code, 200)
        with ZipFile(BytesIO(exported.data)) as archive:
            document = etree.fromstring(archive.read('word/document.xml'))
        self.assertTrue(document.findall('.//w:del', docx_engine.NS))
        self.assertTrue(document.findall('.//w:ins', docx_engine.NS))
        project = self.ok(self.client.post(f"/api/projects/{project['id']}/undo"))
        self.assertEqual(store.document(project['id']), initial)
        self.assertEqual(project['annotations'][0]['end_block_id'], 'p3')
        self.assertEqual(project['annotations'][0]['status'], 'suggested')

    def test_merging_reanchors_suffix_and_later_cross_range_and_flags_overlap(self):
        project = self.create(['PRE red', 'middle', 'blue SUFFIX', 'after ONE', 'after TWO'])
        project, edit = self.mark(project, 'p1', 4, 4, 'p3')
        project, prior = self.mark(project, 'p1', 0, 3)
        project, overlap = self.mark(project, 'p2', 0, 6)
        project, suffix = self.mark(project, 'p3', 5, 11)
        project, later = self.mark(project, 'p4', 6, 9, 'p5')
        project = self.supply(project, edit, 'merged')
        project = self.action(project, edit, 'apply')
        marks = {a['id']: a for a in project['annotations']}
        self.assertEqual(marks[overlap['id']]['status'], 'conflict')
        self.assertEqual(marks[prior['id']]['status'], 'pending')
        moved_suffix = marks[suffix['id']]
        self.assertEqual((moved_suffix['block_id'], moved_suffix['start'], moved_suffix['end']), ('p1', 11, 17))
        self.assertEqual(moved_suffix['status'], 'pending')
        moved_later = marks[later['id']]
        self.assertEqual((moved_later['block_id'], moved_later['end_block_id']), ('p2', 'p3'))
        self.assertEqual(moved_later['status'], 'pending')
        project = self.supply(project, moved_later, 'joined')
        project = self.action(project, moved_later, 'apply')
        self.assertEqual([b['text'] for b in project['blocks']], ['跨段测试', 'PRE merged SUFFIX', 'after joined'])
        project = self.supply(project, moved_suffix, 'TAIL')
        project = self.action(project, moved_suffix, 'apply')
        self.assertEqual(project['blocks'][1]['text'], 'PRE merged TAIL')

    def test_increasing_paragraph_count_reanchors_later_single_range(self):
        project = self.create(['one', 'two', 'later'])
        project, selected = self.mark(project, 'p1', 0, 3, 'p2')
        project, later = self.mark(project, 'p3', 0, 5)
        project = self.supply(project, selected, 'first\r\nsecond\rthird\nfourth')
        self.assertEqual(project['annotations'][0]['replacement'], 'first\nsecond\nthird\nfourth')
        project = self.action(project, selected, 'apply')
        moved = next(a for a in project['annotations'] if a['id'] == later['id'])
        self.assertEqual((moved['block_id'], moved['start'], moved['end'], moved['status']), ('p5', 0, 5, 'pending'))
        self.assertEqual([b['text'] for b in project['blocks'][1:]], ['first', 'second', 'third', 'fourth', 'later'])

    def test_cross_range_adds_one_word_comment_without_changing_text(self):
        project = self.create(['第一段', '中间段', '最后段'])
        project, annotation = self.mark(project, 'p1', 1, 2, 'p3')
        project = self.action(project, annotation, 'comment')
        self.assertEqual(project['stats']['comments'], 1)
        self.assertEqual([b['text'] for b in project['blocks'][1:]], ['第一段', '中间段', '最后段'])
        with ZipFile(BytesIO(store.document(project['id']))) as archive:
            document = etree.fromstring(archive.read('word/document.xml'))
        begin = document.findall('.//w:commentRangeStart', docx_engine.NS)
        end = document.findall('.//w:commentRangeEnd', docx_engine.NS)
        self.assertEqual(len(begin), 1)
        self.assertEqual(len(end), 1)
        self.assertIsNot(begin[0].getparent(), end[0].getparent())
        self.assertEqual(begin[0].get(f'{{{docx_engine.W}}}id'), end[0].get(f'{{{docx_engine.W}}}id'))
        project = self.supply(project, annotation, '合并后的文字')
        project = self.action(project, annotation, 'apply')
        self.assertEqual(project['stats']['comments'], 1)
        self.assertEqual([b['text'] for b in project['blocks'][1:]], ['第合并后的文字段'])

    def test_empty_intermediate_paragraph_is_included(self):
        project = self.create(['开头', '', '结尾'])
        project, annotation = self.mark(project, 'p1', 0, 2, 'p3')
        self.assertEqual(annotation['quote'], '开头\n\n结尾')
        project = self.supply(project, annotation, '合并')
        project = self.action(project, annotation, 'apply')
        self.assertEqual([b['text'] for b in project['blocks'][1:]], ['合并'])

    def test_invalid_or_protected_cross_range_does_not_create_partial_mark(self):
        project = self.create(['开头', '引文[2]保持', '结尾'])
        payload = dict(block_id='p1', start=0, end=2, end_block_id='p3', quote='开头\n引文[2]保持\n结尾')
        for changes in ({}, {'end_block_id': 'p0'}, {'quote': '过期原文'}, {'start': True}, {'end': 99}):
            with self.subTest(changes=changes):
                response = self.client.post(f"/api/projects/{project['id']}/annotations", json=payload | changes)
                self.assertEqual(response.status_code, 400)
        unchanged = self.ok(self.client.get(f"/api/projects/{project['id']}"))
        self.assertEqual(unchanged['version'], project['version'])
        self.assertEqual(unchanged['annotations'], [])


if __name__ == '__main__':
    unittest.main()
