"""Cross-paragraph replacement must retain real Word paragraph-mark revisions."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import sys
import unittest
from zipfile import ZipFile

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import docx_engine as engine


def parts(data):
    with ZipFile(BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def revision_view(data, accept):
    """Independent OOXML final/original view, including paragraph marks.

    A deleted paragraph mark joins the following paragraph when accepted;
    an inserted paragraph mark joins it when rejected. The text revisions
    must remain distinct from those paragraph-mark revisions.
    """
    root = etree.fromstring(parts(data)[engine.MAIN])
    result, pending = [], ''
    for p in root.findall('w:body/w:p', engine.NS):
        def text(node):
            if node.tag == engine._w('pPr'):
                return ''
            if node.tag == engine._w('del') and accept:
                return ''
            if node.tag == engine._w('ins') and not accept:
                return ''
            if node.tag in {engine._w('t'), engine._w('delText')}:
                return node.text or ''
            if node.tag == engine._w('tab'):
                return '\t'
            if node.tag in {engine._w('br'), engine._w('cr')}:
                return '\n'
            return ''.join(text(child) for child in node)
        pending += text(p)
        removed_mark = p.find('w:pPr/w:rPr/w:' + ('del' if accept else 'ins'), engine.NS)
        if removed_mark is None:
            result.append(pending)
            pending = ''
    if pending:
        result.append(pending)
    return result


class MultiBlockDocxTests(unittest.TestCase):
    def test_merge_partial_paragraphs_is_one_reversible_edit(self):
        data = engine.create_document('', ['前缀😀旧的第一句。', '旧的第二句。后缀', '未选择的段落'])
        changed = engine.apply_edit(data, 'p0', 3, 6, '旧的第一句。\n旧的第二句。', '合并后的句子。', end_block_id='p1')
        self.assertEqual([b['text'] for b in engine.read_document(changed)['blocks']], ['前缀😀合并后的句子。后缀', '未选择的段落'])
        self.assertEqual(revision_view(changed, True), ['前缀😀合并后的句子。后缀', '未选择的段落'])
        self.assertEqual(revision_view(changed, False), revision_view(data, True))
        root = engine._package(changed)[1]
        self.assertEqual(len(root.findall('.//w:pPr/w:rPr/w:del', engine.NS)), 1)
        self.assertTrue(root.findall('.//w:del/w:r/w:delText', engine.NS))

    def test_two_paragraphs_can_be_rewritten_as_three_without_soft_breaks(self):
        data = engine.create_document('', ['前缀旧一', '旧二后缀', '尾段'])
        changed = engine.apply_edit(data, 'p0', 2, 2, '旧一\n旧二', '新一\n新二\n新三', end_block_id='p1')
        expected = ['前缀新一', '新二', '新三后缀', '尾段']
        self.assertEqual([b['text'] for b in engine.read_document(changed)['blocks']], expected)
        self.assertEqual(revision_view(changed, True), expected)
        self.assertEqual(revision_view(changed, False), ['前缀旧一', '旧二后缀', '尾段'])
        root = engine._package(changed)[1]
        self.assertEqual(len(root.findall('.//w:pPr/w:rPr/w:ins', engine.NS)), 2)
        self.assertFalse(root.findall('.//w:ins/w:r/w:br', engine.NS))
        ids = root.xpath('//w:ins/@w:id | //w:del/@w:id', namespaces=engine.NS)
        self.assertEqual(len(ids), len(set(ids)))

    def test_delete_across_empty_paragraph_and_boundary_only_range(self):
        data = engine.create_document('', ['保留首旧', '', '旧保留尾', '尾段'])
        changed = engine.apply_edit(data, 'p0', 3, 1, '旧\n\n旧', '', end_block_id='p2')
        self.assertEqual(revision_view(changed, True), ['保留首保留尾', '尾段'])
        self.assertEqual(revision_view(changed, False), ['保留首旧', '', '旧保留尾', '尾段'])
        data = engine.create_document('', ['甲', '乙'])
        changed = engine.apply_edit(data, 'p0', 1, 0, '\n', '', end_block_id='p1')
        self.assertEqual([b['text'] for b in engine.read_document(changed)['blocks']], ['甲乙'])
        self.assertEqual(revision_view(changed, False), ['甲', '乙'])

    def test_multiblock_comment_has_one_anchor_pair_and_preserves_text(self):
        data = engine.create_document('', ['首段末尾', '中间全文', '结尾段落'])
        changed = engine.add_comment(data, 'p0', 2, 2, '末尾\n中间全文\n结尾', '整体调整衔接', end_block_id='p2')
        self.assertEqual([b['text'] for b in engine.read_document(changed)['blocks']], ['首段末尾', '中间全文', '结尾段落'])
        root = engine._package(changed)[1]
        paragraphs = root.findall('w:body/w:p', engine.NS)
        self.assertEqual(len(paragraphs[0].findall('w:commentRangeStart', engine.NS)), 1)
        self.assertEqual(len(paragraphs[2].findall('w:commentRangeEnd', engine.NS)), 1)
        self.assertEqual(len(paragraphs[2].findall('w:r/w:commentReference', engine.NS)), 1)

    def test_selected_quote_is_checked_across_every_paragraph(self):
        data = engine.create_document('', ['第一段', '第二段', '第三段'])
        with self.assertRaisesRegex(ValueError, '原文'):
            engine.apply_edit(data, 'p0', 0, 3, '第一段\n改变了\n第三段', '新文', end_block_id='p2')

    def test_unselected_runs_properties_and_package_parts_are_unchanged(self):
        from docx import Document
        source = Document()
        first = source.add_paragraph(style='Heading 2')
        first.add_run('前缀').bold = True
        first.add_run('旧一')
        last = source.add_paragraph(style='Normal')
        last.add_run('旧二')
        last.add_run('后缀').italic = True
        source.add_paragraph('未选段落', style='Heading 1')
        buffer = BytesIO()
        source.save(buffer)
        data = buffer.getvalue()
        before_root = engine._package(data)[1]
        changed = engine.apply_edit(data, 'p0', 2, 2, '旧一\n旧二', '新一\n新二\n新三', end_block_id='p1')
        after_root = engine._package(changed)[1]
        for label in ('前缀', '后缀'):
            before_run = before_root.xpath('//w:r[w:t/text()=$text]', namespaces=engine.NS, text=label)[0]
            after_run = after_root.xpath('//w:r[w:t/text()=$text]', namespaces=engine.NS, text=label)[0]
            self.assertEqual(etree.tostring(before_run), etree.tostring(after_run))
        paragraphs = after_root.findall('w:body/w:p', engine.NS)
        self.assertEqual(etree.tostring(before_root.findall('w:body/w:p', engine.NS)[-1]), etree.tostring(paragraphs[-1]))
        self.assertEqual([b['style'] for b in engine.read_document(changed)['blocks']], ['Heading2', 'Heading2', 'Normal', 'Heading1'])
        before, after = parts(data), parts(changed)
        for name in before:
            if name not in {engine.MAIN, 'word/settings.xml'}:
                self.assertEqual(before[name], after[name], name)
        self.assertEqual(revision_view(changed, False), ['前缀旧一', '旧二后缀', '未选段落'])

    def test_same_paragraph_count_retains_equal_formatted_text_islands(self):
        from docx import Document
        source = Document()
        for _ in range(2):
            paragraph = source.add_paragraph()
            paragraph.add_run('保留').bold = True
            paragraph.add_run('旧')
        buffer = BytesIO()
        source.save(buffer)
        changed = engine.apply_edit(buffer.getvalue(), 'p0', 0, 3, '保留旧\n保留旧', '保留新\n保留新', end_block_id='p1')
        root = engine._package(changed)[1]
        self.assertEqual(len(root.xpath('//w:r[w:rPr/w:b and w:t/text()="保留"]', namespaces=engine.NS)), 2)
        self.assertEqual(revision_view(changed, True), ['保留新', '保留新'])
        self.assertEqual(revision_view(changed, False), ['保留旧', '保留旧'])

    def test_protected_middle_content_and_section_breaks_are_not_removed(self):
        data = engine.create_document('', ['首段', '引用[12]必须保留', '尾段'])
        with self.assertRaisesRegex(ValueError, '受保护'):
            engine.apply_edit(data, 'p0', 0, 2, '首段\n引用[12]必须保留\n尾段', '重写', end_block_id='p2')
        data = engine.create_document('', ['首段', '尾段'])
        _, root = engine._package(data)
        first = root.find('w:body/w:p', engine.NS)
        props = etree.Element(engine._w('pPr'))
        etree.SubElement(props, engine._w('sectPr'))
        first.insert(0, props)
        data = engine._repack(data, {engine.MAIN: engine._serialize(root)})
        with self.assertRaisesRegex(ValueError, '分节'):
            engine.apply_edit(data, 'p0', 0, 2, '首段\n尾段', '重写', end_block_id='p1')

    def test_same_table_cell_multiblock_is_supported_but_other_cells_are_not_merged(self):
        from docx import Document
        source = Document()
        table = source.add_table(rows=1, cols=2)
        table.cell(0, 0).paragraphs[0].text = '单元格第一段'
        table.cell(0, 0).add_paragraph('单元格第二段')
        table.cell(0, 1).text = '另一个单元格'
        buffer = BytesIO()
        source.save(buffer)
        data = buffer.getvalue()
        changed = engine.apply_edit(data, 'p0', 0, len('单元格第二段'), '单元格第一段\n单元格第二段', '单元格合并段', end_block_id='p1')
        self.assertEqual([b['text'] for b in engine.read_document(changed)['blocks']], ['单元格合并段', '另一个单元格'])
        with self.assertRaisesRegex(ValueError, '单元格'):
            engine.apply_edit(data, 'p1', 0, len('另一个单元格'), '单元格第二段\n另一个单元格', '不能合并', end_block_id='p2')

    def test_full_range_deletion_keeps_one_empty_paragraph_and_rejects_to_original(self):
        data = engine.create_document('', ['第一段', '', '第三段'])
        changed = engine.apply_edit(data, 'p0', 0, 3, '第一段\n\n第三段', '', end_block_id='p2')
        self.assertEqual([b['text'] for b in engine.read_document(changed)['blocks']], [''])
        self.assertEqual(revision_view(changed, True), [''])
        self.assertEqual(revision_view(changed, False), ['第一段', '', '第三段'])

    def test_existing_revision_before_range_survives_and_selected_revision_rejects(self):
        data = engine.create_document('', ['原前缀旧一', '旧二后缀'])
        data = engine.apply_edit(data, 'p0', 0, 1, '原', '新')
        changed = engine.apply_edit(data, 'p0', 3, 2, '旧一\n旧二', '整体改写', end_block_id='p1')
        self.assertEqual([b['text'] for b in engine.read_document(changed)['blocks']], ['新前缀整体改写后缀'])
        self.assertEqual(revision_view(changed, False), ['原前缀旧一', '旧二后缀'])
        with self.assertRaisesRegex(ValueError, '受保护'):
            engine.apply_edit(data, 'p0', 0, 2, '新前缀旧一\n旧二', '重写', end_block_id='p1')


if __name__ == '__main__':
    unittest.main()
