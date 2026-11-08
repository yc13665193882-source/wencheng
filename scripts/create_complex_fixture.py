"""Build a deterministic five-page academic acceptance fixture, using synthetic data.

Run with the Python runtime resolved by load_workspace_dependencies. This builder
does not import the application engine so it can expose engine regressions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import zipfile

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION_START
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from lxml import etree
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
R = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
STAMP = "2024-01-01T00:00:00Z"
NS = {"w": W, "m": M}


def node(tag, text=None, **attrs):
    item = OxmlElement(tag)
    if text is not None:
        item.text = text
    for key, value in attrs.items():
        item.set(qn(key), str(value))
    return item


def wrun(text, deleted=False):
    run = node("w:r")
    value = node("w:delText" if deleted else "w:t", text)
    value.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    run.append(value)
    return run


def mr(text):
    run = node("m:r")
    run.append(node("m:t", text))
    return run


def sub(base, index):
    value = node("m:sSub")
    e, s = node("m:e"), node("m:sub")
    e.append(mr(base))
    s.append(mr(index))
    value.extend((e, s))
    return value


def field(p, instruction, cached, simple=False):
    if simple:
        fld = node("w:fldSimple", **{"w:instr": f" {instruction} ", "w:dirty": "false"})
        fld.append(wrun(cached))
        p._p.append(fld)
        return
    for tag, text in (("begin", None), (None, f" {instruction} "), ("separate", None)):
        run = node("w:r")
        if tag:
            run.append(node("w:fldChar", **{"w:fldCharType": tag}))
        else:
            element = node("w:instrText", text)
            element.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            run.append(element)
        p._p.append(run)
    p._p.append(wrun(cached))
    end = node("w:r")
    end.append(node("w:fldChar", **{"w:fldCharType": "end"}))
    p._p.append(end)


def bookmark(p, name, identifier, callback):
    p._p.append(node("w:bookmarkStart", **{"w:id": identifier, "w:name": name}))
    callback()
    p._p.append(node("w:bookmarkEnd", **{"w:id": identifier}))


def page_setup(section, landscape=False):
    section.orientation = WD_ORIENT.LANDSCAPE if landscape else WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = (Cm(29.7), Cm(21)) if landscape else (Cm(21), Cm(29.7))
    section.top_margin = section.bottom_margin = Cm(1.9)
    section.left_margin = section.right_margin = Cm(2.0)
    section.header_distance = section.footer_distance = Cm(.8)
    # Write an explicit false so host Word preferences cannot imply a first-page variant.
    section._sectPr.get_or_add_titlePg().val = False


def add_note_reference(p, kind):
    run = p.add_run()._r
    props = node("w:rPr")
    props.append(node("w:vertAlign", **{"w:val": "superscript"}))
    run.append(props)
    run.append(node(f"w:{kind}Reference", **{"w:id": "1"}))


def notes_part(kind, text):
    notes = etree.Element(f"{{{W}}}{kind}s", nsmap={"w": W})
    for ident, separator in ((-1, "separator"), (0, "continuationSeparator"), (1, None)):
        value = etree.SubElement(notes, f"{{{W}}}{kind}", {f"{{{W}}}id": str(ident)})
        para = etree.SubElement(value, f"{{{W}}}p")
        if separator:
            value.set(f"{{{W}}}type", separator)
            run = etree.SubElement(para, f"{{{W}}}r")
            etree.SubElement(run, f"{{{W}}}{separator}")
        else:
            para.append(node("w:pPr"))
            reference = node("w:r")
            reference.append(node(f"w:{kind}Ref"))
            para.append(reference)
            para.append(wrun(" " + text))
    return notes


def picture() -> BytesIO:
    """Small deterministic scientific plot; values are synthetic fixture data."""
    image = Image.new("RGB", (900, 310), "white")
    draw = ImageDraw.Draw(image)
    draw.line((65, 35, 65, 250, 855, 250), fill="#333333", width=3)
    for y in (75, 125, 175, 225):
        draw.line((65, y, 855, y), fill="#DDDDDD", width=1)
    points = [(85, 210), (225, 180), (365, 160), (505, 126), (645, 105), (805, 70)]
    draw.line(points, fill="#335F8D", width=5)
    for x, y in points:
        draw.ellipse((x-6, y-6, x+6, y+6), fill="#335F8D")
    draw.text((70, 12), "SYNTHETIC FIXTURE  /  arbitrary units", fill="black")
    for i, (x, _) in enumerate(points, 1):
        draw.text((x-4, 266), str(i), fill="black")
    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output


def editable_case(cases, identifier, location, paragraph, quote, replacement):
    assert paragraph.count(quote) == 1
    cases.append(dict(id=identifier, location=location, paragraph_text=paragraph,
                      quote=quote, replacement=replacement,
                      expected_paragraph=paragraph.replace(quote, replacement, 1),
                      instruction="仅做所示局部精简，保留数字、引文、限定语与段落结构。"))


def build_fixture() -> tuple[bytes, dict]:
    doc = Document()
    doc.settings._element.get_or_add_evenAndOddHeaders().val = False
    page_setup(doc.sections[0])
    fixed_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
    doc.core_properties.title = "复杂论文文档处理合成验收样例"
    doc.core_properties.subject = "Synthetic acceptance fixture only; not actual research"
    doc.core_properties.author = "Wencheng Fixture Builder"
    doc.core_properties.created = doc.core_properties.modified = fixed_date
    for style_name in ("Normal", "Title", "Subtitle", "Heading 1", "Heading 2", "Caption"):
        style = doc.styles[style_name]
        style.font.name = "Times New Roman"
        style.font.color.rgb = RGBColor(0, 0, 0)
        style._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "SimSun")
        style.paragraph_format.space_after = Pt(7)
        for border in list(style._element.xpath("./w:pPr/w:pBdr")):
            border.getparent().remove(border)
    doc.styles["Normal"].font.size = Pt(10.5)
    doc.styles["Normal"].paragraph_format.line_spacing = 1.2
    doc.styles["Title"].font.size = Pt(20)
    doc.styles["Heading 1"].font.size = Pt(14)
    doc.styles["Heading 1"].paragraph_format.space_before = Pt(10)
    doc.styles["Heading 2"].font.size = Pt(11.5)
    doc.styles["Caption"].font.size = Pt(9)
    header = doc.sections[0].header.paragraphs[0]
    header.text = "文澄复杂论文验收样例    合成测试数据"
    header.runs[0].font.size = Pt(8)
    footer = doc.sections[0].footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run("合成样例  第 ")
    field(footer, "PAGE", "1")
    footer.add_run(" 页  共 ")
    field(footer, "NUMPAGES", "5")
    footer.add_run(" 页")
    cases = []

    # Page 1: ordinary prose, headings, multilingual citations and a safe edit.
    doc.add_paragraph("复杂论文文档处理合成验收样例", "Title")
    doc.add_paragraph("Synthetic academic document for preservation testing", "Subtitle")
    doc.add_paragraph("本文件专用于文档处理软件验收。作者、文献、数值和研究情境均为合成测试数据，不代表真实研究结论。验收目标是观察局部文字修改后，排版、批注、修订、公式和引用对象是否保留。")
    doc.add_paragraph("摘要", "Heading 1")
    doc.add_paragraph("样例采用五页结构：第一页为中英文摘要与背景，第二页包含方法、原生公式和小图，第三页为横向宽表，第四页包含讨论与审阅对象，第五页为编号参考文献和尾注。正文与表格各安排受控改写句，修改范围避开受保护的学术对象。")
    doc.add_paragraph("Abstract", "Heading 2")
    doc.add_paragraph("This document is a synthetic acceptance fixture for a local DOCX editing tool. The test compares targeted prose edits with preservation of mathematical objects, citations, notes, fields, bookmarks, comments and prior revisions. The numerical values are fixed test inputs and carry no empirical claim.")
    doc.add_paragraph("1 研究背景", "Heading 1")
    paragraph = "值得注意的是，合成样本的平均误差为 0.24，结果可能受采样间隔影响[1]。"
    doc.add_paragraph(paragraph)
    editable_case(cases, "body_zh", "body", paragraph, "值得注意的是，", "")
    doc.add_paragraph("本验收采用局部修改原则：保留原始数据、术语和限定语，仅精简指定片段。连续文本既包含数字引用 [1, 2]，也包含作者年份引用 (Fixture Author, 2024)。这两类引用均为人工构造，用于检查定位和保护行为。")
    doc.add_paragraph("1.1 检查范围", "Heading 2")
    doc.add_paragraph("正文、表格、页眉与页脚分别承担不同职责。正文提供受控修改位置，表格暴露单元格边界，页眉和页脚用于观察分节后的继承关系。此处不要求软件解释这些对象，只要求修改后仍可由 Word 识别。")
    doc.add_page_break()

    # Page 2: true inline and block OMML, notes, captions and bookmarks.
    doc.add_paragraph("2 合成方法与对象结构", "Heading 1")
    p = doc.add_paragraph("方法段落使用行内原生公式 ")
    inline = node("m:oMath")
    inline.extend((sub("x", "i"), mr("=i/10")))
    p._p.append(inline)
    p.add_run(" 表示固定测试输入。该公式前后的普通文字保持可读，数学对象本身不参与改写。")
    doc.add_paragraph("2.1 原生分式与上下标", "Heading 2")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    display = node("m:oMathPara")
    omath = node("m:oMath")
    omath.extend((sub("y", "i"), mr("=")))
    fraction = node("m:f")
    numerator, denominator = node("m:num"), node("m:den")
    numerator.extend((sub("x", "i"), mr("−μ")))
    denominator.append(mr("σ"))
    fraction.extend((numerator, denominator))
    omath.extend((fraction, mr("+")))
    power = node("m:sSubSup")
    for tag, value in (("m:e", "x"), ("m:sub", "i"), ("m:sup", "2")):
        part = node(tag)
        part.append(mr(value))
        power.append(part)
    omath.append(power)
    display.append(omath)
    p._p.append(display)
    p.add_run("    (1)")
    p = doc.add_paragraph("公式仅用于检验 OMML 分式、下标与上标的结构保留")
    add_note_reference(p, "footnote")
    p.add_run("。分母和指数均为测试符号，不应据此推断测量模型。")
    p = doc.add_paragraph("混合字符样式包含 ")
    p.add_run("加粗术语").bold = True
    p.add_run("、")
    p.add_run("italic variable").italic = True
    p.add_run("、")
    p.add_run("underlined label").underline = True
    p.add_run(" 与 ")
    code = p.add_run("sample_id = A01")
    code.font.name = "Consolas"
    p.add_run("。这些片段的字体和强调样式均属于保留对象。")
    doc.add_paragraph("2.2 图形与交叉引用", "Heading 2")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    drawing = p.add_run().add_picture(picture(), width=Cm(13.5))
    drawing._inline.docPr.set("descr", "Synthetic fixture plot with six fixed points; not experimental data")
    caption = doc.add_paragraph(style="Caption")
    caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption.add_run("图 ")
    bookmark(caption, "FixtureFigure", "20", lambda: field(caption, "SEQ Figure \\* ARABIC", "1", simple=True))
    caption.add_run(" 固定六点合成示意图")
    p = doc.add_paragraph("交叉引用示例见图 ")
    field(p, "REF FixtureFigure \\h", "1")
    p.add_run("，图所在页为 ")
    field(p, "PAGEREF FixtureFigure \\h", "2")
    p.add_run("。域代码及其缓存显示值应同时保留。")

    # Page 3: true section orientation change and a merged wide table.
    section = doc.add_section(WD_SECTION_START.NEW_PAGE)
    page_setup(section, True)
    doc.add_paragraph("3 横向宽表与合并单元格", "Heading 1")
    doc.add_paragraph("表中每一个值均为固定合成数据。横向页面、跨列标题、纵向合并单元格和重复表头用于验证结构；普通说明单元格提供一处可精简的英文开场。")
    caption = doc.add_paragraph(style="Caption")
    caption.add_run("表 ")
    bookmark(caption, "FixtureTable", "21", lambda: field(caption, "SEQ Table \\* ARABIC", "1", simple=True))
    caption.add_run(" 合成验收记录矩阵")
    table = doc.add_table(rows=9, cols=6)
    table.autofit = False
    # A table-level fallback also covers the raw continuation cells of vMerge.
    # python-docx row.cells returns the restart cell for those continuation rows.
    table_borders = node("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        table_borders.append(node(f"w:{side}", **{"w:val": "single", "w:sz": "4", "w:color": "D9D9D9"}))
    table._tbl.tblPr.append(table_borders)
    widths = [Cm(2.0), Cm(2.1), Cm(2.6), Cm(2.6), Cm(3.0), Cm(12.0)]
    for column, width in zip(table.columns, widths):
        column.width = width
    for row in table.rows:
        for cell, width in zip(row.cells, widths):
            cell.width = width
    table.cell(0, 0).merge(table.cell(0, 5)).text = "SYNTHETIC FIXTURE  合成记录  非真实研究结果"
    for c, value in enumerate(("组别", "记录", "输入值", "误差", "条件", "英文说明")):
        table.cell(1, c).text = value
    english = "It is important to note that this synthetic row remains stable."
    for row_index in range(2, 9):
        values = ["A" if row_index < 5 else "B", f"R{row_index-1:02}", f"{row_index/10:.2f}", f"{0.30-row_index/100:.2f}", "固定间隔", english if row_index == 2 else f"Synthetic record {row_index-1}; preserve the stated units and condition."]
        for column, value in enumerate(values):
            table.cell(row_index, column).text = value
    table.cell(2, 0).merge(table.cell(4, 0)).text = "A"
    table.cell(5, 0).merge(table.cell(8, 0)).text = "B"
    styled_cells = set()
    for row_index, row in enumerate(table.rows):
        row._tr.get_or_add_trPr().append(node("w:cantSplit"))
        if row_index < 2:
            row._tr.get_or_add_trPr().append(node("w:tblHeader"))
        for cell in row.cells:
            if cell._tc in styled_cells:
                continue
            styled_cells.add(cell._tc)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            props = cell._tc.get_or_add_tcPr()
            borders = node("w:tcBorders")
            for side in ("top", "left", "bottom", "right"):
                borders.append(node(f"w:{side}", **{"w:val": "single", "w:sz": "4", "w:color": "D9D9D9"}))
            props.append(borders)
            margins = node("w:tcMar")
            for side in ("top", "left", "bottom", "right"):
                margins.append(node(f"w:{side}", **{"w:w": "95", "w:type": "dxa"}))
            props.append(margins)
            if row_index < 2:
                props.append(node("w:shd", **{"w:fill": "DCE6EF"}))
            for para in cell.paragraphs:
                para.paragraph_format.space_after = Pt(2)
                para.paragraph_format.line_spacing = 1.05
                for run in para.runs:
                    run.font.size = Pt(9)
                    if row_index < 2:
                        run.bold = True
    editable_case(cases, "table_en", "table", english, "It is important to note that this", "This")
    doc.add_paragraph("横向页末说明保持在同一分节中。下一页恢复纵向页面，但延续相同页眉、页脚与页码序列。")

    # Page 4: existing annotation/revisions, English prose and final note marker.
    section = doc.add_section(WD_SECTION_START.NEW_PAGE)
    page_setup(section)
    doc.add_paragraph("4 Discussion and review objects", "Heading 1")
    paragraph = "As previously mentioned, the synthetic estimate may change with the sampling interval (Fixture Author, 2024)."
    doc.add_paragraph(paragraph)
    editable_case(cases, "body_en", "body", paragraph, "As previously mentioned, the", "The")
    doc.add_paragraph("The fixture deliberately keeps a scientific hedge in the same paragraph as the editable lead-in. The phrase may change carries the intended uncertainty and must remain in the reviewed output. Author-year references and numeric references [2–4] are independent preservation checks.")
    doc.add_paragraph("4.1 已有普通批注", "Heading 2")
    p = doc.add_paragraph("该句包含")
    p._p.append(node("w:commentRangeStart", **{"w:id": "7"}))
    p.add_run("需要保留原始审稿意见")
    p._p.append(node("w:commentRangeEnd", **{"w:id": "7"}))
    cr = node("w:r")
    cr.append(node("w:commentReference", **{"w:id": "7"}))
    p._p.append(cr)
    p.add_run("的批注锚点。新增修改不应改变这条已有意见的内容和作者。")
    doc.add_paragraph("4.2 已有插入和删除修订", "Heading 2")
    p = doc.add_paragraph("历史审阅记录：此处结论")
    deleted = node("w:del", **{"w:id": "900", "w:author": "Fixture Reviewer", "w:date": STAMP})
    deleted.append(wrun("已经证实", deleted=True))
    inserted = node("w:ins", **{"w:id": "901", "w:author": "Fixture Reviewer", "w:date": STAMP})
    inserted.append(wrun("尚待验证"))
    p._p.extend((deleted, inserted))
    p.add_run("，请保留已有审阅轨迹。")
    paragraph = "需要强调的是，本段只检查普通正文修改，不改变已有审阅轨迹。"
    doc.add_paragraph(paragraph)
    editable_case(cases, "body_review_neighbor", "body", paragraph, "需要强调的是，", "")
    doc.add_paragraph("5 限制与验收方法", "Heading 1")
    p = doc.add_paragraph("本样例用于对象保留验收，不能用于判断真实模型的准确率、误差分布或研究有效性")
    add_note_reference(p, "endnote")
    p.add_run("。验收应同时比较 XML 对象、可见文本和 Word 页面，单纯文本抽取不能发现跨页、字体或公式显示问题。")
    p = doc.add_paragraph("表格定位可通过表 ")
    field(p, "REF FixtureTable \\h", "1")
    p.add_run(" 和页码 ")
    field(p, "PAGEREF FixtureTable \\h", "3")
    p.add_run(" 交叉检查。受控改写完成后，原图、脚注、尾注、引用、批注与既有修订都应仍然存在。")
    doc.add_page_break()

    # Page 5: the numbered heading tests reference-section detection.
    doc.add_paragraph("6 参考文献", "Heading 1")
    references = [
        "[1] Fixture Author A. Synthetic reference for numeric citation testing. Fixture Journal, 2024, 1: 1–2. 合成条目，不对应真实文献。",
        "[2] Fixture Author B, Fixture Author C. Preserving notes and mathematical objects in a test document. Test Proceedings, 2024: 3–4. Synthetic reference only.",
        "[3] 示例作者甲. 用于检查中文参考文献格式的合成条目. 测试文献集, 2024, 2: 5–6. 本条目不代表真实发表记录。",
        "[4] 示例作者乙. 用于检查交叉引用和分节的合成条目. 文档测试记录, 2024, 3: 7–8. 本条目不代表真实发表记录。",
        "Fixture Author. (2024). An invented author-year reference used only for preservation testing. Synthetic Documentation Series, 1, 9–10.",
    ]
    for value in references:
        p = doc.add_paragraph(value)
        p.paragraph_format.space_after = Pt(12)
        p.paragraph_format.left_indent = Cm(.55)
        p.paragraph_format.first_line_indent = Cm(-.55)
    output = BytesIO()
    doc.save(output)
    with zipfile.ZipFile(BytesIO(output.getvalue())) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts["word/footnotes.xml"] = serialize(notes_part("footnote", "合成脚注 1：所有输入值仅用于软件验收，脚注文本应完整保留。"))
    parts["word/endnotes.xml"] = serialize(notes_part("endnote", "Synthetic endnote 1: this is a generated acceptance fixture, not evidence for a research claim."))
    comments = etree.Element(f"{{{W}}}comments", nsmap={"w": W})
    comment = etree.SubElement(comments, f"{{{W}}}comment", {f"{{{W}}}id": "7", f"{{{W}}}author": "Fixture Reviewer", f"{{{W}}}initials": "FR", f"{{{W}}}date": STAMP})
    comment_p = etree.SubElement(comment, f"{{{W}}}p")
    comment_p.append(wrun("原始普通批注：请保留限定语；这条意见用于验收，不能随局部改写丢失。"))
    parts["word/comments.xml"] = serialize(comments)
    rels = etree.fromstring(parts["word/_rels/document.xml.rels"])
    types = etree.fromstring(parts["[Content_Types].xml"])
    for index, kind in enumerate(("footnotes", "endnotes", "comments"), 90):
        etree.SubElement(rels, f"{{{R}}}Relationship", Id=f"rId{index}", Type=f"http://schemas.openxmlformats.org/officeDocument/2006/relationships/{kind}", Target=f"{kind}.xml")
        etree.SubElement(types, f"{{{CT}}}Override", PartName=f"/word/{kind}.xml", ContentType=f"application/vnd.openxmlformats-officedocument.wordprocessingml.{kind}+xml")
    parts["word/_rels/document.xml.rels"] = serialize(rels)
    parts["[Content_Types].xml"] = serialize(types)
    settings = etree.fromstring(parts["word/settings.xml"])
    settings.append(node("w:trackRevisions"))
    settings.append(node("w:updateFields", **{"w:val": "false"}))
    parts["word/settings.xml"] = serialize(settings)
    app_properties = etree.fromstring(parts["docProps/app.xml"])
    pages = app_properties.find("{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Pages")
    if pages is not None:
        pages.text = "5"
    parts["docProps/app.xml"] = serialize(app_properties)
    data = package(parts)
    document = etree.fromstring(parts["word/document.xml"])
    preserve_parts = [name for name in parts if name in ("word/footnotes.xml", "word/endnotes.xml", "word/comments.xml") or name.startswith(("word/header", "word/footer", "word/media/"))]
    inventory = {
        "schema": "wencheng.complex-fixture.v1", "fixture": "complex-academic.docx",
        "synthetic": True, "expected_pages": 5,
        "page_plan": ["portrait introduction", "portrait methods equations image", "landscape merged table", "portrait discussion reviews", "portrait numbered references and endnote"],
        "editable_cases": cases,
        "preserve_parts": [{"part": name, "sha256": hashlib.sha256(parts[name]).hexdigest()} for name in sorted(preserve_parts)],
        "protected_objects": {
            "inline_math_count": len(document.xpath("//m:oMath[not(parent::m:oMathPara)]", namespaces=NS)),
            "display_math_count": len(document.xpath("//m:oMathPara", namespaces=NS)),
            "fraction_count": len(document.xpath("//m:f", namespaces=NS)),
            "subscript_count": len(document.xpath("//m:sSub", namespaces=NS)),
            "subsuperscript_count": len(document.xpath("//m:sSubSup", namespaces=NS)),
            "footnote_ids": ["1"], "endnote_ids": ["1"], "comment_ids": ["7"],
            "bookmark_names": ["FixtureFigure", "FixtureTable"],
            "field_instructions": ["SEQ Figure \\* ARABIC", "SEQ Table \\* ARABIC", "REF FixtureFigure \\h", "PAGEREF FixtureFigure \\h", "REF FixtureTable \\h", "PAGEREF FixtureTable \\h"],
            "footer_field_instructions": ["PAGE", "NUMPAGES"],
            "original_revisions": [{"type":"del", "id":"900", "text":"已经证实"}, {"type":"ins", "id":"901", "text":"尚待验证"}],
            "reference_heading": "6 参考文献", "reference_entries": references,
            "citation_texts": ["[1]", "[1, 2]", "[2–4]", "(Fixture Author, 2024)"],
            "table_count": 1, "table_rows": 9, "table_grid_columns": 6,
            "section_count": 3, "section_orientations": ["portrait", "landscape", "portrait"],
            "manual_page_breaks": 2, "image_count": 1,
            "mixed_style_texts": ["加粗术语", "italic variable", "underlined label", "sample_id = A01"],
        },
        "visual_qa": {"status":"pending_word_render", "note":"Five pages are an intended layout, not a page-count claim before Word rendering."},
    }
    return data, inventory


def serialize(element):
    return etree.tostring(element, encoding="UTF-8", xml_declaration=True, standalone=True)


def package(parts):
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(parts):
            info = zipfile.ZipInfo(name, (2024, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, parts[name])
    return output.getvalue()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "tests" / "fixtures" / "complex-academic.docx")
    args = parser.parse_args()
    data, inventory = build_fixture()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    manifest = args.output.with_suffix(".inventory.json")
    manifest.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"docx":str(args.output.resolve()), "inventory":str(manifest.resolve()), "editable_cases":len(inventory["editable_cases"])}, ensure_ascii=False))
