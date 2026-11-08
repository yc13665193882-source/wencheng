"""Conservative DOCX text edits backed by the original OOXML package.

Offsets are Python Unicode code-point offsets into ``read_document`` block text.
Deleted runs are omitted from that text; inserted runs are visible and protected.
Unsupported structures are preserved and exposed as protected ranges.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
from io import BytesIO
import posixpath
import re
from zipfile import BadZipFile, ZipFile

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
R = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
XML = "http://www.w3.org/XML/1998/namespace"
NS = {"w": W, "m": M}
REL_BASE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
MAIN = "word/document.xml"


def _w(name):
    return f"{{{W}}}{name}"


def _xml(data):
    return etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))


def _serialize(root):
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)


def _package(data):
    try:
        with ZipFile(BytesIO(data)) as z:
            files = {name: z.read(name) for name in z.namelist()}
        root = _xml(files[MAIN])
        if root.find(_w("body")) is None:
            raise ValueError("DOCX 缺少正文。")
        return files, root
    except (BadZipFile, KeyError, etree.XMLSyntaxError) as exc:
        raise ValueError("无法读取 DOCX，请选择未加密的 Word 文档。") from exc


def _repack(original, changes):
    out = BytesIO()
    with ZipFile(BytesIO(original)) as source, ZipFile(out, "w") as dest:
        dest.comment = source.comment
        for info in source.infolist():
            dest.writestr(info, changes.get(info.filename, source.read(info.filename)))
        for name, content in changes.items():
            if name not in source.namelist():
                dest.writestr(name, content)
    return out.getvalue()


def _paragraphs(root):
    return list(root.find(_w("body")).iter(_w("p")))


def _ancestor(node, tag):
    return next((a for a in node.iterancestors() if a.tag == tag), None)


def _style(p):
    node = p.find("w:pPr/w:pStyle", NS)
    return node.get(_w("val"), "Normal") if node is not None else "Normal"


def _heading(style):
    return bool(re.match(r"^(heading|标题|Title|Subtitle)", style, re.I))


def _heading_level(p):
    outline = p.find("w:pPr/w:outlineLvl", NS)
    if outline is not None and outline.get(_w("val"), "").isdigit():
        level = int(outline.get(_w("val")))
        return level + 1 if level < 9 else None
    match = re.match(r"^(?:heading|标题)\s*(\d+)", _style(p), re.I)
    return int(match[1]) if match else (1 if _heading(_style(p)) else None)


def _reference_heading(text):
    # Heading numbers may be literal text rather than Word numbering properties.
    text = re.sub(r"^\s*(?:第\s*[〇零一二三四五六七八九十百\d]+\s*[章节篇部]|"
                  r"(?:\d+(?:\.\d+)*|[IVXLCDM]+|[一二三四五六七八九十]+)[.)、．]?)\s*", "", text)
    label = re.sub(r"[\s:：/／()（）\[\]【】—–\-]+", "", text).casefold()
    return bool(re.fullmatch(r"(?:参考文献|references|bibliography){1,2}", label))


def _citation_ranges(text):
    # Match conventional author–year forms, not arbitrary parentheses with dates.
    latin_name = r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+(?:\s+[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+){0,2}"
    name = rf"(?:{latin_name}|[\u3400-\u9fff]{{2,4}})"
    authors = rf"{name}(?:\s*(?:,\s*|&|and|、|和|与)\s*{name})*(?:\s+et\s+al\.?|等)?"
    years = r"\d{4}[a-z]?(?:\s*[,，]\s*\d{4}[a-z]?)*"
    pair = rf"{authors}\s*[,，]\s*{years}"
    patterns = [r"\[(?:\d+[\s,，;；\-–—]*)+\]",
                rf"[（(]\s*{pair}(?:\s*[;；]\s*{pair})*\s*[）)]",
                rf"(?<![\w]){authors}\s*[（(]\s*{years}\s*[）)]"]
    return [{"start": m.start(), "end": m.end(), "kind": "citation"}
            for pattern in patterns for m in re.finditer(pattern, text)]


def _scan(p, field_state=None):
    """Extract visible text and retain a map to original text nodes and runs."""
    field_state = field_state if field_state is not None else {"depth": 0}
    atoms, protected, chunks = [], [], []
    offset = 0
    scope_protection = None
    if _ancestor(p, _w("txbxContent")) is not None:
        scope_protection = "text-box"
    elif _ancestor(p, _w("sdt")) is not None:
        scope_protection = "content-control"

    def add(node, text, run, reason=None):
        nonlocal offset
        start = offset
        offset += len(text)
        chunks.append(text)
        atom = {"node": node, "run": run, "text": text, "start": start, "end": offset,
                "reason": reason or scope_protection}
        atoms.append(atom)
        if atom["reason"]:
            protected.append({"start": start, "end": offset, "kind": atom["reason"]})

    def visit(node, reason=None, run=None):
        tag = node.tag
        if tag in {_w("pPr"), _w("rPr")}:
            return
        if tag in {_w("del"), _w("moveFrom")}:
            protected.append({"start": offset, "end": offset, "kind": "revision"})
            return
        boundary_kind = {
            "bookmarkStart": "bookmark", "bookmarkEnd": "bookmark",
            "commentRangeStart": "comment", "commentRangeEnd": "comment",
            "moveFromRangeStart": "revision", "moveFromRangeEnd": "revision",
            "moveToRangeStart": "revision", "moveToRangeEnd": "revision",
        }.get(etree.QName(node).localname)
        if boundary_kind:
            protected.append({"start": offset, "end": offset, "kind": boundary_kind})
            return
        if tag == _w("p") and node is not p:
            return  # Textbox paragraphs are reported as their own protected blocks.
        if tag in {f"{{{M}}}oMath", f"{{{M}}}oMathPara"}:
            text = "".join(node.itertext()).strip()
            add(node, "〔公式" + ("：" + text if text else "") + "〕", run, "formula")
            return
        if tag in {_w("drawing"), _w("pict"), _w("object")}:
            add(node, "〔图形〕", run, "object")
            return
        if tag == _w("r"):
            if node.find("w:rPr/w:rPrChange", NS) is not None:
                reason = "revision"
            for child in node:
                visit(child, reason, node)
            return
        if tag == _w("fldChar"):
            kind = node.get(_w("fldCharType"))
            if kind == "begin":
                field_state["depth"] += 1
                protected.append({"start": offset, "end": offset, "kind": "field"})
            elif kind == "end":
                protected.append({"start": offset, "end": offset, "kind": "field"})
                field_state["depth"] = max(0, field_state["depth"] - 1)
            return
        if tag in {_w("instrText"), _w("delInstrText"), _w("delText")}:
            return
        if tag == _w("t"):
            add(node, node.text or "", run, reason or ("field" if field_state["depth"] else None))
            return
        if tag in {_w("tab"), _w("br"), _w("cr")}:
            layout_break = tag == _w("br") and node.get(_w("type"), "textWrapping") != "textWrapping"
            add(node, "\t" if tag == _w("tab") else "\n", run,
                reason or ("layout" if layout_break else None) or ("field" if field_state["depth"] else None))
            return
        if tag == _w("ptab"):
            add(node, "\t", run, "layout")
            return
        if tag in {_w("noBreakHyphen"), _w("softHyphen")}:
            add(node, "\u2011" if tag == _w("noBreakHyphen") else "\u00ad", run, "symbol")
            return
        if tag in {_w("footnoteReference"), _w("endnoteReference")}:
            kind = "footnote" if tag == _w("footnoteReference") else "endnote"
            label = "脚注" if kind == "footnote" else "尾注"
            add(node, f"〔{label}{node.get(_w('id'), '')}〕", run, kind)
            return
        if tag == _w("sym"):
            add(node, "〔符号〕", run, "symbol")
            return
        next_reason = reason
        if tag in {_w("ins"), _w("moveTo")}:
            next_reason = "revision"
        elif tag == _w("fldSimple"):
            protected.append({"start": offset, "end": offset, "kind": "field"})
            next_reason = "field"
        elif tag == _w("hyperlink"):
            next_reason = "hyperlink"
        elif tag in {_w("sdt"), _w("sdtContent")}:
            next_reason = "content-control"
        elif tag != _w("p") and len(node):
            # Unknown wrappers cannot be rewritten without understanding their schema.
            next_reason = next_reason or "structure"
        for child in node:
            visit(child, next_reason, run)

    visit(p)
    text = "".join(chunks)
    protected.extend(_citation_ranges(text))
    return {"text": text, "atoms": atoms, "protected": _merge_ranges(protected)}


def _merge_ranges(ranges):
    result = []
    for item in sorted(ranges, key=lambda x: (x["start"], x["end"], x["kind"])):
        if (result and result[-1]["kind"] == item["kind"] and
                item["start"] <= result[-1]["end"]):
            result[-1]["end"] = max(result[-1]["end"], item["end"])
        elif item not in result:
            result.append(dict(item))
    return result


def _scans(root):
    result, reference_level = [], None
    fields = {"depth": 0}
    for p in _paragraphs(root):
        scan = _scan(p, fields)
        style = _style(p)
        level = _heading_level(p)
        if _reference_heading(scan["text"]):
            reference_level = level or 1
        elif reference_level is not None and level is not None and level <= reference_level:
            reference_level = None
        if reference_level is not None or re.search(r"bibliography|footnote|endnote|参考文献|脚注|尾注", style, re.I):
            scan["protected"].append({"start": 0, "end": len(scan["text"]), "kind": "references"})
        scan["paragraph"] = p
        scan["paragraphs"] = [p]
        if p.find('w:pPr/w:rPr/w:del', NS) is not None or p.find('w:pPr/w:rPr/w:ins', NS) is not None:
            scan['protected'].append({'start': len(scan['text']), 'end': len(scan['text']), 'kind': 'revision'})
        # A deleted paragraph mark joins the following paragraph in Word's
        # accepted view. Keep the physical nodes for reversible OOXML editing.
        previous = result[-1]['paragraphs'][-1] if result else None
        if (previous is not None and previous.getnext() is p and
                previous.find('w:pPr/w:rPr/w:del', NS) is not None):
            joined = result[-1]
            offset = len(joined['text'])
            joined['text'] += scan['text']
            joined['atoms'].extend(dict(atom, start=atom['start'] + offset, end=atom['end'] + offset) for atom in scan['atoms'])
            joined['protected'].extend(dict(item, start=item['start'] + offset, end=item['end'] + offset) for item in scan['protected'])
            joined['paragraphs'].append(p)
            joined['paragraph'] = p
        else:
            result.append(scan)
    return result


def _related_path(files, kind, default):
    path = "word/_rels/document.xml.rels"
    if path in files:
        root = _xml(files[path])
        for rel in root:
            if rel.get("Type") == REL_BASE + kind and rel.get("TargetMode") != "External":
                return posixpath.normpath(posixpath.join("word", rel.get("Target", default))).lstrip("/")
    return default


def read_document(data: bytes) -> dict:
    files, root = _package(data)
    scans = _scans(root)
    blocks = []
    containers = {}
    for i, scan in enumerate(scans):
        p, text = scan["paragraph"], scan["text"]
        style = _style(p)
        cell = _ancestor(p, _w("tc"))
        kind = "table-cell" if cell is not None else ("heading" if _heading(style) else "paragraph")
        protected = _merge_ranges(scan["protected"])
        covered = set()
        for r in protected:
            covered.update(range(r["start"], r["end"]))
        block = {"id": f"p{i}", "text": text, "kind": kind, "style": style,
                 "editable": bool(text) and len(covered) < len(text), "protected": protected,
                 "container_id": containers.setdefault(p.getparent(), f"c{len(containers)}"),
                 "section_break": scan['paragraphs'][-1].find('w:pPr/w:sectPr', NS) is not None,
                 "runs": []}
        for atom in scan["atoms"]:
            run = atom["run"]
            props = run.find(_w("rPr")) if run is not None else None
            fmt = {}
            if props is not None:
                for key, tag in [("bold", "b"), ("italic", "i"), ("underline", "u")]:
                    value = props.find(_w(tag))
                    fmt[key] = value is not None and value.get(_w("val"), "1") not in {"0", "false", "none"}
            block["runs"].append({"text": atom["text"], "start": atom["start"], "end": atom["end"], **fmt})
        if cell is not None:
            row = _ancestor(cell, _w("tr"))
            table = _ancestor(cell, _w("tbl"))
            block.update(table_id=f"t{list(root.iter(_w('tbl'))).index(table)}",
                         row=list(table.iterchildren(_w("tr"))).index(row),
                         column=list(row.iterchildren(_w("tc"))).index(cell))
        blocks.append(block)
    comments_path = _related_path(files, "comments", "word/comments.xml")
    comments_count = len(_xml(files[comments_path]).findall(_w("comment"))) if comments_path in files else 0
    counts = {
        "formula": len(root.findall(".//m:oMath", NS)),
        "footnote": len(root.findall(".//w:footnoteReference", NS)),
        "endnote": len(root.findall(".//w:endnoteReference", NS)),
        "field": len(root.findall(".//w:fldSimple", NS)) + len(root.findall(".//w:fldChar[@w:fldCharType='begin']", NS)),
        "comment": comments_count,
        "revision": sum(len(root.findall(f".//w:{tag}", NS)) for tag in
                        ("ins", "del", "moveFrom", "moveTo", "rPrChange", "pPrChange", "tblPrChange", "trPrChange", "tcPrChange", "sectPrChange")),
        "references": sum(any(r["kind"] == "references" for r in b["protected"]) for b in blocks),
        "object": len(root.findall(".//w:drawing", NS)) + len(root.findall(".//w:pict", NS)),
    }
    return {"blocks": blocks, "protections": [{"kind": k, "count": v} for k, v in counts.items() if v],
            "stats": {"paragraphs": len(blocks), "characters": sum(len(b["text"]) for b in blocks),
                      "tables": len(root.findall(".//w:tbl", NS)), "comments": comments_count,
                      "revisions": counts["revision"]}}


def selection_range(doc, block_id, start, end, quote, end_block_id=None, *, allow_empty=False, check_protected=True):
    """Validate a visible range; offsets belong to the first and last blocks.

    Paragraph boundaries are represented by a single newline in exported text.
    This also keeps legacy, single-block annotations valid without migration.
    """
    blocks = doc['blocks']
    indexes = {block['id']: i for i, block in enumerate(blocks)}
    if not isinstance(block_id, str) or (end_block_id is not None and not isinstance(end_block_id, str)):
        raise ValueError('无效的段落标识。')
    last_id = end_block_id if end_block_id is not None else block_id
    if block_id not in indexes or last_id not in indexes:
        raise ValueError('段落已不存在，请刷新文档。')
    first, last = indexes[block_id], indexes[last_id]
    if (first > last or not isinstance(start, int) or not isinstance(end, int)
            or isinstance(start, bool) or isinstance(end, bool)):
        raise ValueError('选区位置无效。')
    chosen = blocks[first:last + 1]
    if not 0 <= start <= len(chosen[0]['text']) or not 0 <= end <= len(chosen[-1]['text']):
        raise ValueError('选区超出段落范围。')
    if first == last and (start > end or (not allow_empty and start == end)):
        raise ValueError('请选择有效文字。')
    if first != last and check_protected:
        scopes = {block.get('container_id', (block.get('table_id'), block.get('row'), block.get('column'))) for block in chosen}
        if len(scopes) != 1:
            raise ValueError('跨段修改须位于连续正文或同一表格单元格内，不能跨越表格结构。')
        if any(block.get('section_break') for block in chosen[:-1]):
            raise ValueError('选区跨越分节符，请在同一节内修改。')
    segments = []
    for index, block in enumerate(chosen):
        left = start if index == 0 else 0
        right = end if index == len(chosen) - 1 else len(block['text'])
        segments.append(dict(block_id=block['id'], start=left, end=right, quote=block['text'][left:right]))
        if check_protected:
            for protected in block.get('protected', []):
                a, b = protected['start'], protected['end']
                overlap = left < b and right > a if left != right else a < left < b
                if a == b:
                    overlap = left < a < right
                    # The end marker is selected when the next paragraph is
                    # part of the same range, even if this paragraph is empty.
                    overlap = overlap or (index < len(chosen) - 1 and a == right)
                if overlap:
                    raise ValueError(f"选区包含受保护内容（{protected['kind']}），请选择相邻正文文字。")
    actual = '\n'.join(segment['quote'] for segment in segments)
    if not isinstance(quote, str) or actual != quote:
        raise ValueError('原文已改变，请重新选择文字。')
    if not allow_empty and not actual:
        raise ValueError('请选择有效文字。')
    return dict(blocks=chosen, segments=segments, text='\n'.join(block['text'] for block in chosen),
                quote=actual, start_index=first, end_index=last)


def _target(root, block_id, start, end, expected, *, allow_empty=True):
    if not isinstance(block_id, str) or not re.fullmatch(r"p\d+", block_id):
        raise ValueError("无效的段落标识。")
    scans = _scans(root)
    index = int(block_id[1:])
    if index >= len(scans):
        raise ValueError("段落已不存在，请刷新文档。")
    scan = scans[index]
    if not isinstance(start, int) or not isinstance(end, int) or isinstance(start, bool) or isinstance(end, bool):
        raise ValueError("选区位置必须是整数。")
    if not (0 <= start <= end <= len(scan["text"])) or (not allow_empty and start == end):
        raise ValueError("选区超出段落范围。")
    if scan["text"][start:end] != expected:
        raise ValueError("原文已改变，请重新选择后再修改。")
    for item in scan["protected"]:
        a, b = item["start"], item["end"]
        overlap = (start < b and end > a) if start != end else (a < start < b)
        if a == b:
            overlap = start < a < end
        if overlap:
            raise ValueError(f"选区包含受保护内容（{item['kind']}），请只选择相邻正文文字。")
    for atom in scan["atoms"]:
        if atom["start"] < end and atom["end"] > start:
            if atom["run"] is None or atom["run"].getparent() not in scan['paragraphs']:
                raise ValueError("该选区位于复杂结构中，暂不能局部修改。")
    return scan


def _run_like(run, children):
    result = etree.Element(_w("r"), attrib=dict(run.attrib))
    props = run.find(_w("rPr"))
    if props is not None:
        result.append(deepcopy(props))
    for child in children:
        result.append(child)
    return result


def _text_node(tag, text, source=None):
    node = etree.Element(tag, attrib=dict(source.attrib) if source is not None else {})
    node.set(f"{{{XML}}}space", "preserve")
    node.text = text
    return node


def _text_children(text, deleted=False):
    result = []
    for item in re.split(r"([\n\t])", text.replace("\r\n", "\n").replace("\r", "\n")):
        if item == "\n":
            result.append(etree.Element(_w("br")))
        elif item == "\t":
            result.append(etree.Element(_w("tab")))
        elif item:
            result.append(_text_node(_w("delText" if deleted else "t"), item))
    return result


def _next_id(root):
    return max((int(v) for v in root.xpath("//@w:id", namespaces=NS) if re.fullmatch(r"\d+", v)), default=0) + 1


def _revision(kind, runs, identifier, author):
    node = etree.Element(_w(kind), attrib={_w("id"): str(identifier), _w("author"): author,
                         _w("date"): datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")})
    node.extend(runs)
    return node


def _wire_part(files, changes, kind, target, content_type):
    relpath = "word/_rels/document.xml.rels"
    relroot = _xml(changes.get(relpath, files.get(relpath))) if changes.get(relpath, files.get(relpath)) else etree.Element(f"{{{R}}}Relationships", nsmap={None: R})
    if not any(n.get("Type") == REL_BASE + kind for n in relroot):
        ids = {n.get("Id") for n in relroot}
        n = 1
        while f"rId{n}" in ids:
            n += 1
        etree.SubElement(relroot, f"{{{R}}}Relationship", Id=f"rId{n}", Type=REL_BASE + kind,
                         Target=posixpath.relpath(target, "word"))
        changes[relpath] = _serialize(relroot)
    types = _xml(changes.get("[Content_Types].xml", files["[Content_Types].xml"]))
    if not any(n.get("PartName") == "/" + target for n in types):
        etree.SubElement(types, f"{{{CT}}}Override", PartName="/" + target, ContentType=content_type)
        changes["[Content_Types].xml"] = _serialize(types)


def _enable_tracking(files, changes):
    path = _related_path(files, "settings", "word/settings.xml")
    settings = _xml(files[path]) if path in files else etree.Element(_w("settings"), nsmap={"w": W})
    if settings.find(_w("trackRevisions")) is None:
        # CT_Settings is ordered; tracking precedes compatibility and layout settings.
        preceding = set("writeProtection view zoom removePersonalInformation removeDateAndTime "
                        "doNotDisplayPageBoundaries displayBackgroundShape printPostScriptOverText "
                        "printFractionalCharacterWidth printFormsData embedTrueTypeFonts embedSystemFonts "
                        "saveSubsetFonts saveFormsData mirrorMargins alignBordersAndEdges "
                        "bordersDoNotSurroundHeader bordersDoNotSurroundFooter gutterAtTop "
                        "hideSpellingErrors hideGrammaticalErrors activeWritingStyle proofState "
                        "formsDesign attachedTemplate linkStyles stylePaneFormatFilter "
                        "stylePaneSortMethod documentType mailMerge revisionView".split())
        at = max((i + 1 for i, child in enumerate(settings)
                  if etree.QName(child).localname in preceding), default=0)
        settings.insert(at, etree.Element(_w("trackRevisions")))
        changes[path] = _serialize(settings)
    _wire_part(files, changes, "settings", path,
               "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml")


def apply_edit(data: bytes, block_id: str, start: int, end: int, expected: str,
               replacement: str, author: str = "文澄", end_block_id: str | None = None) -> bytes:
    if not isinstance(replacement, str):
        raise ValueError("修改内容必须是文本。")
    if end_block_id is not None and end_block_id != block_id:
        return _apply_multiblock_edit(data, block_id, start, end, expected, replacement, author, end_block_id)
    files, root = _package(data)
    scan = _target(root, block_id, start, end, expected)
    if expected == replacement:
        return data
    # Keep equal words and their original runs in place. Replacing an entire
    # selection with one new run would discard bold/italic islands inside it.
    token_pattern = r"\s+|[A-Za-zÀ-ÖØ-öø-ÿ]+(?:['’][A-Za-zÀ-ÖØ-öø-ÿ]+)*|\d+(?:\.\d+)*|."
    old_tokens = re.findall(token_pattern, expected, re.S)
    new_tokens = re.findall(token_pattern, replacement, re.S)
    old_offsets, new_offsets = [0], [0]
    for token in old_tokens:
        old_offsets.append(old_offsets[-1] + len(token))
    for token in new_tokens:
        new_offsets.append(new_offsets[-1] + len(token))
    changes = SequenceMatcher(None, old_tokens, new_tokens, autojunk=False).get_opcodes()
    for mode, i, j, a, b in reversed(changes):
        if mode == "equal":
            continue
        left, right = start + old_offsets[i], start + old_offsets[j]
        old = expected[old_offsets[i]:old_offsets[j]]
        new = replacement[new_offsets[a]:new_offsets[b]]
        scan = _target(root, block_id, left, right, old)
        _apply_range(root, scan, left, right, new, author,
                     insertion_side="start" if left == start else "end")
    package_changes = {MAIN: _serialize(root)}
    _enable_tracking(files, package_changes)
    return _repack(data, package_changes)


def _mark_paragraph_boundary(root, paragraph, kind, author):
    """Track a paragraph mark, not its text (ISO/IEC 29500 §17.13.5)."""
    props = paragraph.find(_w('pPr'))
    if props is None:
        props = etree.Element(_w('pPr'))
        paragraph.insert(0, props)
    mark = props.find(_w('rPr'))
    if mark is None:
        mark = etree.Element(_w('rPr'))
        # CT_PPr places paragraph-mark properties before section properties.
        after = next((i for i, child in enumerate(props) if child.tag in {_w('sectPr'), _w('pPrChange')}), len(props))
        props.insert(after, mark)
    for old in list(mark):
        if old.tag in {_w('del'), _w('ins')}:
            mark.remove(old)
    mark.append(_revision(kind, [], _next_id(root), author))


def _apply_multiblock_edit(data, block_id, start, end, expected, replacement, author, end_block_id):
    selected = selection_range(read_document(data), block_id, start, end, expected, end_block_id)
    replacement = replacement.replace('\r\n', '\n').replace('\r', '\n')
    files, root = _package(data)
    targets = [_target(root, item['block_id'], item['start'], item['end'], item['quote'])
               for item in selected['segments']]
    physical = [p for scan in targets for p in scan['paragraphs']]
    if any(left.getnext() is not right for left, right in zip(physical, physical[1:])):
        raise ValueError('跨段修改不能越过表格或复杂文档结构。')
    if any(p.find('w:pPr/w:sectPr', NS) is not None for p in physical[:-1]):
        raise ValueError('选区跨越分节符，请在同一节内修改。')
    if expected == replacement:
        return data
    lines = replacement.split('\n')
    # When paragraph boundaries stay put, retain the existing word-level diff
    # so equal text islands keep their bold/italic run properties.
    if len(lines) == len(targets) and all('\n' not in item['quote'] for item in selected['segments']):
        for item, line in reversed(list(zip(selected['segments'], lines))):
            data = apply_edit(data, item['block_id'], item['start'], item['end'], item['quote'], line, author)
        return data

    # Install the start marker before deletion. This preserves the exact side
    # of a run boundary even when a complete paragraph becomes deleted text.
    marker = etree.Element(_w('bookmarkStart'))
    template = _insert_boundary(targets[0]['paragraph'], targets[0], start, marker)
    start_paragraph = marker.getparent()
    template = template if template is not None else etree.Element(_w('r'))
    for item in reversed(selected['segments']):
        if item['start'] == item['end']:
            continue
        scan = _target(root, item['block_id'], item['start'], item['end'], item['quote'])
        _apply_range(root, scan, item['start'], item['end'], '', author)
    # Retain each original paragraph and its formatting for Word's Reject
    # operation; only its delimiter is deleted in the accepted view.
    for paragraph in physical[:-1]:
        if paragraph.find('w:pPr/w:rPr/w:del', NS) is None:
            _mark_paragraph_boundary(root, paragraph, 'del', author)

    def insert_text(paragraph, value):
        if value:
            paragraph.append(_revision('ins', [_run_like(template, _text_children(value))], _next_id(root), author))

    if len(lines) == 1:
        if replacement:
            start_paragraph.replace(marker, _revision('ins', [_run_like(template, _text_children(replacement))], _next_id(root), author))
        else:
            start_paragraph.remove(marker)
    else:
        # A new paragraph delimiter splits the physical start paragraph.
        # Its trailing original nodes and original paragraph mark move to the
        # last split piece. Rejecting inserted marks therefore rejoins the
        # original paragraph with its original properties intact.
        parent = start_paragraph.getparent()
        original_props = start_paragraph.find(_w('pPr'))
        original_props = deepcopy(original_props) if original_props is not None else None
        tail = list(start_paragraph)[start_paragraph.index(marker) + 1:]
        for node in tail:
            start_paragraph.remove(node)
        start_paragraph.remove(marker)
        insert_text(start_paragraph, lines[0])
        _mark_paragraph_boundary(root, start_paragraph, 'ins', author)
        previous = start_paragraph
        for i, line in enumerate(lines[1:], 1):
            paragraph = etree.Element(_w('p'), {name: value for name, value in start_paragraph.attrib.items()
                                                 if etree.QName(name).localname not in {'paraId', 'textId'}})
            if original_props is not None:
                paragraph.append(deepcopy(original_props))
            parent.insert(parent.index(previous) + 1, paragraph)
            insert_text(paragraph, line)
            if i == len(lines) - 1:
                paragraph.extend(tail)
            else:
                _mark_paragraph_boundary(root, paragraph, 'ins', author)
            previous = paragraph
    package_changes = {MAIN: _serialize(root)}
    _enable_tracking(files, package_changes)
    return _repack(data, package_changes)


def _apply_range(root, scan, start, end, replacement, author, insertion_side="start"):
    p, identifier = scan["paragraph"], _next_id(root)
    if start == end:
        marker = etree.Element(_w("bookmarkStart"))
        nearby = _insert_boundary(p, scan, start, marker, side=insertion_side)
        template = nearby if nearby is not None else etree.Element(_w("r"))
        insertion = _revision("ins", [_run_like(template, _text_children(replacement))], identifier, author)
        marker.getparent().replace(marker, insertion)
    else:
        mapping = {id(a["node"]): a for a in scan["atoms"]}
        selected_runs = []
        for a in scan["atoms"]:
            if a["start"] < end and a["end"] > start and a["run"] not in selected_runs:
                selected_runs.append(a["run"])
        inserted = False
        for run in selected_runs:
            p = run.getparent()
            groups = []

            def push(mode, child):
                if groups and groups[-1][0] == mode:
                    groups[-1][1].append(child)
                else:
                    groups.append((mode, [child]))

            for child in run:
                if child.tag == _w("rPr"):
                    continue
                atom = mapping.get(id(child))
                if atom is None or atom["end"] <= start or atom["start"] >= end:
                    push("keep", deepcopy(child))
                    continue
                a, b = max(start, atom["start"]) - atom["start"], min(end, atom["end"]) - atom["start"]
                if child.tag == _w("t"):
                    value = child.text or ""
                    if a:
                        push("keep", _text_node(_w("t"), value[:a], child))
                    if b > a:
                        push("delete", _text_node(_w("delText"), value[a:b], child))
                    if b < len(value):
                        push("keep", _text_node(_w("t"), value[b:], child))
                elif child.tag in {_w("tab"), _w("br"), _w("cr")}:
                    push("delete", deepcopy(child))
                else:
                    raise ValueError("选区包含不可改写的文档元素。")
            position = p.index(run)
            p.remove(run)
            for mode, children in groups:
                newrun = _run_like(run, children)
                if mode == "delete":
                    node = _revision("del", [newrun], identifier, author)
                    identifier += 1
                else:
                    node = newrun
                p.insert(position, node)
                position += 1
                if mode == "delete" and not inserted:
                    if replacement:
                        p.insert(position, _revision("ins", [_run_like(run, _text_children(replacement))], identifier, author))
                        identifier += 1
                        position += 1
                    inserted = True


def _insert_boundary(p, scan, offset, marker, side="start"):
    """Insert an annotation marker at a visible-text offset, splitting one run."""
    left = [a for a in scan["atoms"] if a["start"] < offset <= a["end"]]
    right = [a for a in scan["atoms"] if a["start"] <= offset < a["end"]]
    candidates = (right + left) if side == "start" else (left + right)
    for atom in candidates:
        if atom["start"] <= offset <= atom["end"]:
            run = atom["run"]
            if run is None or run.getparent() not in scan.get('paragraphs', [p]):
                continue
            if atom["reason"]:
                continue
            p = run.getparent()
            left, right = [], []
            passed = False
            for child in run:
                if child.tag == _w("rPr"):
                    continue
                if child is not atom["node"]:
                    (right if passed else left).append(deepcopy(child))
                else:
                    if offset == atom["start"]:
                        right.append(deepcopy(child))
                    elif offset == atom["end"]:
                        left.append(deepcopy(child))
                    elif child.tag != _w("t"):
                        raise ValueError("标记边界不能位于文档对象内部。")
                    else:
                        cut = offset - atom["start"]
                        left.append(_text_node(_w("t"), (child.text or "")[:cut], child))
                        right.append(_text_node(_w("t"), (child.text or "")[cut:], child))
                    passed = True
            index = p.index(run)
            p.remove(run)
            for node in ([_run_like(run, left)] if left else []) + [marker] + ([_run_like(run, right)] if right else []):
                p.insert(index, node)
                index += 1
            return run
    if scan["atoms"]:
        raise ValueError("标记边界位于受保护结构中。")
    p.append(marker)
    return None


def add_comment(data: bytes, block_id: str, start: int, end: int, expected: str,
                text: str, author: str = "文澄", end_block_id: str | None = None) -> bytes:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("批注内容不能为空。")
    files, root = _package(data)
    selected = selection_range(read_document(data), block_id, start, end, expected, end_block_id)
    targets = [_target(root, item['block_id'], item['start'], item['end'], item['quote'])
               for item in selected['segments']]
    path = _related_path(files, "comments", "word/comments.xml")
    comments = _xml(files[path]) if path in files else etree.Element(_w("comments"), nsmap={"w": W})
    identifier = _next_id(comments)
    scan = targets[-1]
    p = scan["paragraph"]
    finish = etree.Element(_w("commentRangeEnd"), {_w("id"): str(identifier)})
    _insert_boundary(p, scan, end, finish, side="end")
    finish_paragraph = finish.getparent()
    # Boundary splits preserve visible offsets, but the node map must be refreshed.
    scan = _scans(root)[int(block_id[1:])]
    begin = etree.Element(_w("commentRangeStart"), {_w("id"): str(identifier)})
    _insert_boundary(scan['paragraph'], scan, start, begin)
    ref = etree.Element(_w("r"))
    etree.SubElement(ref, _w("commentReference"), {_w("id"): str(identifier)})
    finish_paragraph.insert(finish_paragraph.index(finish) + 1, ref)
    comment = etree.SubElement(comments, _w("comment"), {_w("id"): str(identifier), _w("author"): author,
        _w("date"): datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")})
    cp = etree.SubElement(comment, _w("p"))
    cr = etree.SubElement(cp, _w("r"))
    cr.extend(_text_children(text))
    changes = {MAIN: _serialize(root), path: _serialize(comments)}
    _wire_part(files, changes, "comments", path,
               "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml")
    return _repack(data, changes)


def create_document(title: str, paragraphs: list[str]) -> bytes:
    from docx import Document
    from docx.shared import Pt
    document = Document()
    document.styles["Normal"].font.name = "Calibri"
    document.styles["Normal"].font.size = Pt(11)
    document.styles["Normal"]._element.get_or_add_rPr().rFonts.set(_w("eastAsia"), "宋体")
    if title:
        document.add_paragraph(title, style="Title")
    for text in paragraphs:
        document.add_paragraph(str(text))
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def append_paragraph(data: bytes, text: str, style: str | None = None) -> bytes:
    _, root = _package(data)
    body = root.find(_w("body"))
    p = etree.Element(_w("p"))
    if style:
        props = etree.SubElement(p, _w("pPr"))
        etree.SubElement(props, _w("pStyle"), {_w("val"): style})
    run = etree.SubElement(p, _w("r"))
    run.extend(_text_children(text))
    sect = body.find(_w("sectPr"))
    if sect is None:
        body.append(p)
    else:
        body.insert(body.index(sect), p)
    return _repack(data, {MAIN: _serialize(root)})
