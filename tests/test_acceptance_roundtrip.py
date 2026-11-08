"""Complex-paper HTTP acceptance and independent preservation-auditor checks."""
from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.acceptance_roundtrip import (MAIN, NS, W, canonical, field_runs,
    inspect_preservation, paragraphs, parts, related_part, run_acceptance, xml)


def replace_part(package: bytes, name: str, content: bytes) -> bytes:
    result = BytesIO()
    with ZipFile(BytesIO(package)) as source, ZipFile(result, "w") as dest:
        for info in source.infolist():
            dest.writestr(info, content if info.filename == name else source.read(info.filename))
    return result.getvalue()


class ComplexPaperAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = (ROOT / "test-output").resolve()
        base.mkdir(exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix="complex-acceptance-test-", dir=base)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.output = Path(cls.temporary.name)
        cls.source = (ROOT / "tests/fixtures/complex-academic.docx").read_bytes()
        cls.inventory = json.loads((ROOT / "tests/fixtures/complex-academic.inventory.json").read_text(encoding="utf-8"))
        cls.audit = run_acceptance(ROOT / "tests/fixtures/complex-academic.docx",
            ROOT / "tests/fixtures/complex-academic.inventory.json", cls.output)
        cls.exported = (cls.output / "exported.docx").read_bytes()
        cls.edits = next(item["edits"] for item in cls.audit["checks"] if item["id"] == "workflow.body_and_table_exact_marks")
        references = set(cls.inventory["protected_objects"]["reference_entries"])
        cls.reference_blocks = {f"p{index}" for index, paragraph in enumerate(paragraphs(xml(parts(cls.source)[MAIN])))
            if "".join(paragraph.xpath(".//w:t/text()", namespaces=NS)) in references}

    def inspect(self, data):
        return {item["id"]: item for item in inspect_preservation(self.source, data,
            edits=self.edits, reference_blocks=self.reference_blocks, new_comments=[self.edits[0]["instruction"]])}

    def test_full_http_workflow_and_artifact_audit(self):
        self.assertTrue(self.audit["passed"], json.dumps({"summary": self.audit["summary"],
            "error": self.audit.get("error"), "failures": [c for c in self.audit["checks"] if not c["passed"]]}, ensure_ascii=False))
        self.assertGreaterEqual(len(self.audit["checks"]), 30)
        self.assertEqual((self.output / "no-op-export.docx").read_bytes(), self.source)
        self.assertNotEqual(self.exported, self.source)
        self.assertEqual(json.loads((self.output / "audit.json").read_text(encoding="utf-8")), self.audit)

    def test_auditor_detects_lost_objects_not_only_counts(self):
        cases = ("math", "field_cache", "footnote", "old_comment", "reference")
        for kind in cases:
            with self.subTest(kind=kind):
                package = parts(self.exported)
                if kind == "footnote":
                    name = related_part(package, "footnotes")
                    root = xml(package[name])
                    root.xpath(".//w:t", namespaces=NS)[-1].text = "corrupted footnote"
                    expected_check = "objects.footnotes_part"
                elif kind == "old_comment":
                    name = related_part(package, "comments")
                    root = xml(package[name])
                    original_id = self.inventory["protected_objects"]["comment_ids"][0]
                    root.xpath("./w:comment[@w:id=$id]//w:t", namespaces=NS, id=original_id)[0].text = "corrupted comment"
                    expected_check = "objects.original_comments"
                else:
                    name = MAIN
                    root = xml(package[name])
                    if kind == "math":
                        root.xpath(".//m:t", namespaces=NS)[0].text = "corrupted equation"
                        expected_check = "objects.omml"
                    elif kind == "field_cache":
                        cached = next(run for run in field_runs(root) if run.find(f"{{{W}}}t") is not None)
                        cached.find(f"{{{W}}}t").text = "999"
                        expected_check = "objects.field_cached_runs"
                    else:
                        index = int(sorted(self.reference_blocks)[0][1:])
                        paragraphs(root)[index].xpath(".//w:t", namespaces=NS)[0].text = "corrupted reference"
                        expected_check = "objects.reference_paragraphs"
                modified = replace_part(self.exported, name, etree.tostring(root, encoding="UTF-8", xml_declaration=True))
                self.assertFalse(self.inspect(modified)[expected_check]["passed"])

    def test_comments_compare_semantics_and_keep_visible_spaces(self):
        package = parts(self.exported)
        name = related_part(package, "comments")
        formatted = etree.tostring(xml(package[name]), encoding="UTF-8", xml_declaration=True, pretty_print=True)
        checks = self.inspect(replace_part(self.exported, name, formatted))
        self.assertTrue(checks["objects.original_comments"]["passed"])
        self.assertTrue(checks["changes.new_comment_valid"]["passed"])
        first = xml(f'<w:r xmlns:w="{W}"><w:t xml:space="preserve"> a </w:t></w:r>'.encode())
        second = xml(f'<w:r xmlns:w="{W}"><w:t xml:space="preserve">a</w:t></w:r>'.encode())
        self.assertNotEqual(canonical(first), canonical(second))


if __name__ == "__main__":
    unittest.main()
