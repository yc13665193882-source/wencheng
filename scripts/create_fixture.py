"""Build a small bilingual DOCX fixture with protected academic structures."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree
from backend.docx_engine import add_comment, _package, _repack, _serialize, _wire_part, W, M


def build_fixture() -> bytes:
    doc = Document()
    doc.add_paragraph("双语文档修订验证", "Title")
    doc.add_paragraph("需要强调的是，本研究需要强调的是，结果支持上述判断。")
    p = doc.add_paragraph()
    p.add_run("格式测试 ")
    p.add_run("bold original").bold = True
    p.add_run(" and ")
    p.add_run("italic text").italic = True
    p.add_run(" remain.")
    p = doc.add_paragraph("公式前的正文需要精简。")
    math = etree.SubElement(p._p, f"{{{M}}}oMath")
    mr = etree.SubElement(math, f"{{{M}}}r")
    etree.SubElement(mr, f"{{{M}}}t").text = "E=mc²"
    p.add_run("公式后的普通文字。")
    p = doc.add_paragraph("正文带脚注")
    ref = OxmlElement("w:footnoteReference")
    ref.set(qn("w:id"), "1")
    p.add_run()._r.append(ref)
    p.add_run("，引用内容应保留。")
    p = doc.add_paragraph("请参见图 ")
    for kind, text in [("begin", None), (None, " REF FigureOne "), ("separate", None)]:
        r = p.add_run()._r
        if kind:
            field = OxmlElement("w:fldChar")
            field.set(qn("w:fldCharType"), kind)
        else:
            field = OxmlElement("w:instrText")
            field.text = text
        r.append(field)
    p.add_run("1")
    r = p.add_run()._r
    field = OxmlElement("w:fldChar")
    field.set(qn("w:fldCharType"), "end")
    r.append(field)
    p.add_run("，相关结果见文献 [1]。")
    table = doc.add_table(rows=2, cols=2)
    table.style = "Table Grid"
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "说明"
    table.cell(1, 0).text = "结果"
    table.cell(1, 1).text = "It is important to note that the results are consistent."
    doc.add_paragraph("References", "Heading 1")
    doc.add_paragraph("[1] Example Author. A preserved reference. 2024.")
    doc.sections[0].header.paragraphs[0].text = "页眉保留 / Preserved header"
    out = BytesIO()
    doc.save(out)
    data = out.getvalue()
    files, root = _package(data)
    footnotes = etree.Element(f"{{{W}}}footnotes", nsmap={"w": W})
    for identifier, kind in [(-1, "separator"), (0, "continuationSeparator"), (1, None)]:
        attrs = {f"{{{W}}}id": str(identifier)}
        if kind:
            attrs[f"{{{W}}}type"] = kind
        note = etree.SubElement(footnotes, f"{{{W}}}footnote", attrs)
        para = etree.SubElement(note, f"{{{W}}}p")
        run = etree.SubElement(para, f"{{{W}}}r")
        if kind:
            etree.SubElement(run, f"{{{W}}}{kind}")
        else:
            etree.SubElement(run, f"{{{W}}}t").text = "必须原样保留的脚注内容。"
    changes = {"word/footnotes.xml": _serialize(footnotes)}
    _wire_part(files, changes, "footnotes", "word/footnotes.xml",
               "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml")
    data = _repack(data, changes)
    data = add_comment(data, "p1", 0, 6, "需要强调的是", "原始批注，应在后续修改中保留。", "原作者")
    return data


if __name__ == "__main__":
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests" / "fixtures" / "academic-bilingual.docx"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(build_fixture())
    print(dest)
