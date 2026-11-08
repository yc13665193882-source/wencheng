from io import BytesIO
from pathlib import Path
import sys
import unittest
from zipfile import ZipFile

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.docx_engine import (read_document, apply_edit, add_comment, create_document,
                                  append_paragraph, NS, W, M)
from scripts.create_fixture import build_fixture


def parts(data):
    with ZipFile(BytesIO(data)) as z:
        return {name: z.read(name) for name in z.namelist()}


def root(data):
    return etree.fromstring(parts(data)["word/document.xml"])


class DocxEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = build_fixture()

    def test_fixture_exposes_academic_objects_and_table(self):
        result = read_document(self.fixture)
        counts = {x["kind"]: x["count"] for x in result["protections"]}
        self.assertEqual(counts["formula"], 1)
        self.assertEqual(counts["footnote"], 1)
        self.assertEqual(counts["field"], 1)
        self.assertEqual(counts["comment"], 1)
        self.assertTrue(any(b["kind"] == "table-cell" for b in result["blocks"]))
        self.assertFalse(result["blocks"][-1]["editable"])

    def test_precise_duplicate_phrase_selection(self):
        old = read_document(self.fixture)["blocks"][1]["text"]
        start = old.index("需要强调的是", 6)
        new = apply_edit(self.fixture, "p1", start, start + 7, "需要强调的是，", "")
        self.assertEqual(read_document(new)["blocks"][1]["text"], "需要强调的是，本研究结果支持上述判断。")
        xml = root(new)
        self.assertEqual("".join(xml.xpath("//w:delText/text()", namespaces=NS)), "需要强调的是，")
        self.assertEqual(len(xml.findall(".//w:commentRangeStart", NS)), 1)

    def test_untouched_parts_and_formula_are_preserved(self):
        before = parts(self.fixture)
        new = apply_edit(self.fixture, "p3", 0, 11, "公式前的正文需要精简。", "公式前的正文。")
        after = parts(new)
        for name, value in before.items():
            if name not in {"word/document.xml", "word/settings.xml"}:
                self.assertEqual(after[name], value, name)
        original_math = root(self.fixture).find(".//m:oMath", NS)
        changed_math = root(new).find(".//m:oMath", NS)
        self.assertEqual(etree.tostring(original_math), etree.tostring(changed_math))

    def test_cross_run_edit_preserves_run_formatting(self):
        text = read_document(self.fixture)["blocks"][2]["text"]
        start = text.index("original")
        end = text.index(" text")
        new = apply_edit(self.fixture, "p2", start, end, text[start:end], "revised")
        p = root(new).findall(".//w:body/w:p", NS)[2]
        self.assertTrue(p.findall(".//w:del/w:r/w:rPr/w:b", NS))
        self.assertTrue(p.findall(".//w:del/w:r/w:rPr/w:i", NS))
        self.assertTrue(p.findall(".//w:ins/w:r/w:rPr/w:b", NS))
        self.assertEqual(read_document(new)["blocks"][2]["text"], "格式测试 bold revised text remain.")

    def test_protected_ranges_reject_but_adjacent_text_can_change(self):
        for block in read_document(self.fixture)["blocks"]:
            for protected in block["protected"]:
                if protected["end"] > protected["start"]:
                    a, b = protected["start"], protected["end"]
                    with self.assertRaises(ValueError):
                        apply_edit(self.fixture, block["id"], a, b, block["text"][a:b], "changed")
        field_block = read_document(self.fixture)["blocks"][5]
        new = apply_edit(self.fixture, "p5", 0, 3, "请参见", "参见")
        self.assertEqual(read_document(new)["blocks"][5]["text"], field_block["text"].replace("请参见", "参见", 1))

    def test_stale_expected_text_rejected(self):
        with self.assertRaises(ValueError):
            apply_edit(self.fixture, "p1", 0, 2, "不符", "修改")

    def test_sequential_revisions_and_existing_revision_protection(self):
        data = create_document("", ["First phrase and second phrase."])
        data = apply_edit(data, "p0", 0, 5, "First", "Initial")
        text = read_document(data)["blocks"][0]["text"]
        start = text.index("second")
        data = apply_edit(data, "p0", start, start + 6, "second", "next")
        self.assertEqual(read_document(data)["blocks"][0]["text"], "Initial phrase and next phrase.")
        with self.assertRaises(ValueError):
            apply_edit(data, "p0", 0, 7, "Initial", "Again")
        ids = root(data).xpath("//w:ins/@w:id | //w:del/@w:id", namespaces=NS)
        self.assertEqual(len(ids), len(set(ids)))

    def test_comment_wiring_and_existing_comment_preservation(self):
        before = parts(self.fixture)
        data = add_comment(self.fixture, "p2", 5, 18, "bold original", "改为简洁表达", "审阅者")
        after = parts(data)
        comments = etree.fromstring(after["word/comments.xml"])
        self.assertEqual(len(comments), 2)
        self.assertEqual(etree.tostring(etree.fromstring(before["word/comments.xml"])[0]), etree.tostring(comments[0]))
        self.assertEqual(read_document(data)["blocks"][2]["text"], read_document(self.fixture)["blocks"][2]["text"])
        ids = root(data).xpath("//w:commentRangeStart/@w:id", namespaces=NS)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sorted(ids), sorted(root(data).xpath("//w:commentRangeEnd/@w:id", namespaces=NS)))
        self.assertIn(b"comments.xml", after["word/_rels/document.xml.rels"])

    def test_table_edit_and_new_paragraph(self):
        block = next(b for b in read_document(self.fixture)["blocks"] if b["text"].startswith("It is important"))
        prefix = "It is important to note that the"
        data = apply_edit(self.fixture, block["id"], 0, len(prefix), prefix, "The")
        self.assertIn("The results are consistent.", [b["text"] for b in read_document(data)["blocks"]])
        data = append_paragraph(data, "新段落 / New paragraph 😀")
        self.assertEqual(read_document(data)["blocks"][-1]["text"], "新段落 / New paragraph 😀")
        body = root(data).find(f"{{{W}}}body")
        self.assertEqual(body[-1].tag, f"{{{W}}}sectPr")

    def test_unicode_offsets_and_insertion(self):
        data = create_document("", ["中文😀 mixed text"])
        data = apply_edit(data, "p0", 4, 9, "mixed", "English")
        self.assertEqual(read_document(data)["blocks"][0]["text"], "中文😀 English text")
        data = apply_edit(data, "p0", 0, 0, "", "前缀 ")
        self.assertEqual(read_document(data)["blocks"][0]["text"], "前缀 中文😀 English text")


if __name__ == "__main__":
    unittest.main()
