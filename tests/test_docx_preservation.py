"""Regressions for academic OOXML structures at editable text boundaries."""
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

W, NS = engine.W, engine.NS


def element(tag, text=None, **attrs):
    node = etree.Element(engine._w(tag), {engine._w(k): str(v) for k, v in attrs.items()})
    node.text = text
    return node


def run(text=None, *, bold=False, italic=False, children=()):
    node = element("r")
    if bold or italic:
        props = etree.SubElement(node, engine._w("rPr"))
        if bold:
            etree.SubElement(props, engine._w("b"))
        if italic:
            etree.SubElement(props, engine._w("i"))
    if text is not None:
        node.append(element("t", text))
    node.extend(children)
    return node


def paragraph(*children, style=None):
    p = element("p")
    if style:
        props = etree.SubElement(p, engine._w("pPr"))
        props.append(element("pStyle", val=style))
    p.extend(children)
    return p


def document(*paragraphs):
    data = engine.create_document("", [])
    _, root = engine._package(data)
    body = root.find(engine._w("body"))
    for p in reversed(paragraphs):
        body.insert(0, deepcopy(p))
    return engine._repack(data, {engine.MAIN: engine._serialize(root)})


def parts(data):
    with ZipFile(BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def xml(data):
    return engine._package(data)[1]


def block(data, index=0):
    return engine.read_document(data)["blocks"][index]


def visible_between(root, start_name, end_name, identifier):
    """Extract accepted-view text inside one paragraph's OOXML anchor markers."""
    nodes = list(root.find(".//w:body/w:p", NS))
    start = next(i for i, n in enumerate(nodes) if n.tag == engine._w(start_name) and n.get(engine._w("id")) == str(identifier))
    end = next(i for i, n in enumerate(nodes) if n.tag == engine._w(end_name) and n.get(engine._w("id")) == str(identifier))
    holder = paragraph(*(deepcopy(n) for n in nodes[start + 1:end]))
    return engine._scan(holder)["text"]


class AcademicPreservationTests(unittest.TestCase):
    def test_numbered_and_bilingual_bibliography_headings(self):
        for title in ("7. References", "VII Bibliography", "第七章 参考文献", "参考文献 / References", "References（参考文献）", "7.2 参考文献 (Bibliography)"):
            with self.subTest(title=title):
                data = document(paragraph(run(title), style="Heading1"), paragraph(run("Smith, A. (2020). Methods.")),
                                paragraph(run("Appendix"), style="Heading1"), paragraph(run("Editable appendix.")))
                self.assertFalse(block(data, 1)["editable"])
                self.assertTrue(block(data, 3)["editable"])
                with self.assertRaises(ValueError):
                    engine.apply_edit(data, "p1", 0, 5, "Smith", "Jones")

    def test_bibliography_subheading_keeps_entries_protected(self):
        data = document(paragraph(run("References"), style="Heading1"),
                        paragraph(run("Primary sources"), style="Heading2"), paragraph(run("Smith, A. Methods.")),
                        paragraph(run("Appendix"), style="Heading1"), paragraph(run("Ordinary text.")))
        self.assertFalse(block(data, 2)["editable"])
        self.assertTrue(block(data, 4)["editable"])

    def test_author_year_citations_are_protected_but_neighbor_is_editable(self):
        for citation in ("(Smith, 2020)", "(Fixture Author, 2024)", "(Smith et al., 2020; Wang, 2021)", "Smith et al. (2020)",
                         "（张三等，2021）", "张三等（2021）", "(Smith & Jones, 2020a, 2020b)"):
            with self.subTest(citation=citation):
                data = document(paragraph(run("Evidence: " + citation + " supports this result.")))
                protected = [p for p in block(data)["protected"] if p["kind"] == "citation"]
                self.assertTrue(protected)
                self.assertEqual(block(data)["text"][protected[0]["start"]:protected[0]["end"]], citation)
                with self.assertRaises(ValueError):
                    at = block(data)["text"].index("202")
                    engine.apply_edit(data, "p0", at, at + 4, block(data)["text"][at:at + 4], "2024")
                changed = engine.apply_edit(data, "p0", 0, 8, "Evidence", "Findings")
                self.assertIn(citation, block(changed)["text"])
        prose = document(paragraph(run("A note (This method was invented in 2020) remains editable.")))
        self.assertFalse(any(p["kind"] == "citation" for p in block(prose)["protected"]))

    def test_bookmark_boundary_crossing_is_rejected_and_inside_edit_stays_inside(self):
        data = document(paragraph(run("Intro "), element("bookmarkStart", id=4, name="Target"), run("Target"),
                                  element("bookmarkEnd", id=4), run(" tail")))
        with self.assertRaises(ValueError):
            engine.apply_edit(data, "p0", 0, 12, "Intro Target", "Result")
        changed = engine.apply_edit(data, "p0", 6, 12, "Target", "Result")
        self.assertEqual(visible_between(xml(changed), "bookmarkStart", "bookmarkEnd", 4), "Result")
        self.assertEqual(xml(changed).find(".//w:bookmarkStart", NS).get(engine._w("name")), "Target")

    def test_original_comment_anchor_stays_on_edited_text(self):
        data = engine.add_comment(document(paragraph(run("Intro Target tail"))), "p0", 6, 12, "Target", "Original reviewer")
        original_comments = parts(data)["word/comments.xml"]
        with self.assertRaises(ValueError):
            engine.apply_edit(data, "p0", 0, 12, "Intro Target", "Result")
        changed = engine.apply_edit(data, "p0", 6, 12, "Target", "Result")
        self.assertEqual(parts(changed)["word/comments.xml"], original_comments)
        self.assertEqual(visible_between(xml(changed), "commentRangeStart", "commentRangeEnd", 1), "Result")

    def test_minimal_insertions_stay_within_bookmark_boundaries(self):
        for replacement in ("New Target", "Target again", "New Target again"):
            with self.subTest(replacement=replacement):
                data = document(paragraph(run("Intro "), element("bookmarkStart", id=4, name="Target"), run("Target"),
                                          element("bookmarkEnd", id=4), run(" tail")))
                changed = engine.apply_edit(data, "p0", 6, 12, "Target", replacement)
                self.assertEqual(visible_between(xml(changed), "bookmarkStart", "bookmarkEnd", 4), replacement)
                self.assertEqual(block(changed)["text"], "Intro " + replacement + " tail")

    def test_comment_next_to_existing_revision_uses_plain_text_side(self):
        data = engine.apply_edit(document(paragraph(run("Old plain text"))), "p0", 0, 3, "Old", "New")
        before_revision = etree.tostring(xml(data).find(".//w:ins", NS))
        changed = engine.add_comment(data, "p0", 3, 9, " plain", "Review this text")
        self.assertEqual(block(changed)["text"], "New plain text")
        self.assertEqual(etree.tostring(xml(changed).find(".//w:ins", NS)), before_revision)
        self.assertEqual(visible_between(xml(changed), "commentRangeStart", "commentRangeEnd", 1), " plain")

    def test_comment_boundaries_do_not_capture_adjacent_field_controls(self):
        field = [element("fldChar", fldCharType="begin"), element("instrText", " REF Target "),
                 element("fldChar", fldCharType="separate"), element("t", "1"), element("fldChar", fldCharType="end")]
        for prefix in (True, False):
            with self.subTest(prefix=prefix):
                children = [element("t", "plain")] + field if prefix else field + [element("t", "plain")]
                data = document(paragraph(run(children=children)))
                start = 0 if prefix else 1
                changed = engine.add_comment(data, "p0", start, start + 5, "plain", "Note")
                p = xml(changed).find(".//w:body/w:p", NS)
                nodes = list(p)
                a = next(i for i, n in enumerate(nodes) if n.tag == engine._w("commentRangeStart"))
                b = next(i for i, n in enumerate(nodes) if n.tag == engine._w("commentRangeEnd"))
                self.assertFalse(any(n.findall(".//w:fldChar", NS) for n in nodes[a + 1:b]))

    def test_deleted_and_move_source_boundaries_are_preserved(self):
        for kind in ("del", "moveFrom"):
            with self.subTest(kind=kind):
                change = element(kind, id=21, author="Original author")
                change.append(run(children=[element("delText" if kind == "del" else "t", "removed")]))
                data = document(paragraph(run("left"), change, run("right")))
                with self.assertRaises(ValueError):
                    engine.apply_edit(data, "p0", 0, 9, "leftright", "combined")
                changed = engine.apply_edit(data, "p0", 4, 9, "right", "after")
                self.assertEqual(etree.tostring(xml(data).find(f".//w:{kind}", NS)),
                                 etree.tostring(xml(changed).find(f".//w:{kind}[@w:id='21']", NS)))

    def test_run_property_revision_is_not_cloned_into_new_revisions(self):
        revised = run("formatted", bold=True)
        old_props = element("rPrChange", id=31, author="Original author")
        old_props.append(element("rPr"))
        revised.find(engine._w("rPr")).append(old_props)
        data = document(paragraph(revised, run(" plain")))
        with self.assertRaises(ValueError):
            engine.apply_edit(data, "p0", 0, 4, "form", "style")
        changed = engine.apply_edit(data, "p0", 10, 15, "plain", "prose")
        self.assertEqual(len(xml(changed).findall(".//w:rPrChange", NS)), 1)
        self.assertGreaterEqual(engine.read_document(data)["stats"]["revisions"], 1)

    def test_move_destination_and_its_range_markers_survive_neighbor_edit(self):
        moved = element("moveTo", id=42, author="Original author")
        moved.append(run("moved"))
        data = document(paragraph(run("before "), element("moveToRangeStart", id=41, name="Move"), moved,
                                  element("moveToRangeEnd", id=41), run(" after")))
        self.assertEqual(block(data)["text"], "before moved after")
        with self.assertRaises(ValueError):
            engine.apply_edit(data, "p0", 7, 12, "moved", "changed")
        changed = engine.apply_edit(data, "p0", 13, 18, "after", "later")
        for tag in ("moveTo", "moveToRangeStart", "moveToRangeEnd"):
            self.assertEqual(etree.tostring(xml(data).find(f".//w:{tag}", NS)),
                             etree.tostring(xml(changed).find(f".//w:{tag}", NS)))
        self.assertEqual(engine.read_document(data)["stats"]["revisions"], 1)

    def test_empty_field_is_a_protected_zero_width_boundary(self):
        data = document(paragraph(run("left"), element("fldSimple", instr=" REF missing "), run("right")))
        with self.assertRaises(ValueError):
            engine.apply_edit(data, "p0", 0, 9, "leftright", "combined")

    def test_page_break_is_preserved_and_not_replaced_as_a_line_break(self):
        data = document(paragraph(run("before", children=[element("br", type="page"), element("t", "after")])))
        with self.assertRaises(ValueError):
            engine.apply_edit(data, "p0", 0, 12, "before\nafter", "before after")
        changed = engine.apply_edit(data, "p0", 7, 12, "after", "later")
        self.assertEqual(xml(changed).find(".//w:br", NS).get(engine._w("type")), "page")

    def test_special_hyphens_are_visible_and_preserved(self):
        data = document(paragraph(run("non", children=[element("noBreakHyphen"), element("t", "breaking"),
                                                          element("softHyphen"), element("t", " text")])))
        self.assertEqual(block(data)["text"], "non\u2011breaking\u00ad text")
        changed = engine.apply_edit(data, "p0", 14, 18, "text", "prose")
        for tag in ("noBreakHyphen", "softHyphen"):
            self.assertIsNotNone(xml(changed).find(f".//w:{tag}", NS))

    def test_positional_tab_has_visible_protected_offset(self):
        tab = element("ptab", alignment="right", relativeTo="margin", leader="none")
        data = document(paragraph(run("left", children=[tab, element("t", "right")])))
        self.assertEqual(block(data)["text"], "left\tright")
        with self.assertRaises(ValueError):
            engine.apply_edit(data, "p0", 0, 10, "left\tright", "combined")
        changed = engine.apply_edit(data, "p0", 5, 10, "right", "after")
        self.assertEqual(etree.tostring(xml(data).find(".//w:ptab", NS)),
                         etree.tostring(xml(changed).find(".//w:ptab", NS)))

    def test_broad_rewrite_preserves_unchanged_formatted_words(self):
        data = document(paragraph(run("We carefully "), run("measure", bold=True), run(" the "), run("signal", italic=True), run(".")))
        old = block(data)["text"]
        changed = engine.apply_edit(data, "p0", 0, len(old), old, "We measure the signal precisely.")
        self.assertEqual(block(changed)["text"], "We measure the signal precisely.")
        measure = [r for r in block(changed)["runs"] if "measure" in r["text"]]
        signal = [r for r in block(changed)["runs"] if "signal" in r["text"]]
        self.assertTrue(measure and all(r.get("bold") for r in measure))
        self.assertTrue(signal and all(r.get("italic") for r in signal))
        self.assertNotIn("measure", "".join(xml(changed).xpath("//w:delText/text()", namespaces=NS)))


if __name__ == "__main__":
    unittest.main()
