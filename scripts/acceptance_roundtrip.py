"""Exercise the complex DOCX fixture through HTTP and write a structural audit.

Run from the project root: ``python scripts/acceptance_roundtrip.py``.
The suggestions are deterministic fixture data, not a call to an AI provider.
This verifies the package and editing workflow; it does not certify Word layout.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import importlib
import json
import os
from pathlib import Path
import posixpath
import sys
import tempfile
from unittest.mock import patch
from zipfile import ZipFile

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NS = {"w": W, "m": M}
MAIN = "word/document.xml"


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def parts(data: bytes) -> dict[str, bytes]:
    with ZipFile(BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def xml(data: bytes):
    return etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))


def canonical(node) -> bytes:
    """Compare XML semantics without attribute order or namespace-declaration noise.

    Do not strip run text: spaces inside Word text nodes matter. Ignore only
    formatting whitespace between elements, where Word stores no visible text.
    Exclusive C14N prevents inherited, unused namespace declarations from making
    an unchanged comment look different after the package is serialized.
    """
    normalized = deepcopy(node)
    text_tags = {f"{{{W}}}{tag}" for tag in ("t", "delText", "instrText", "delInstrText")}
    text_tags.add(f"{{{M}}}t")
    for child in normalized.iter():
        if child.tag not in text_tags and child.text is not None and not child.text.strip():
            child.text = None
        if child.tail is not None and not child.tail.strip():
            child.tail = None
    return etree.tostring(normalized, method="c14n", exclusive=True, with_comments=False)


def signatures(nodes) -> list[str]:
    return [digest(canonical(node)) for node in nodes]


def paragraphs(root):
    return list(root.find(f"{{{W}}}body").iter(f"{{{W}}}p"))


def related_part(package: dict[str, bytes], kind: str) -> str | None:
    data = package.get("word/_rels/document.xml.rels")
    if data is None:
        return None
    for rel in xml(data):
        if rel.get("Type", "").endswith("/" + kind) and rel.get("TargetMode") != "External":
            target = rel.get("Target", "")
            return target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("word", target))
    return None


def field_runs(root):
    """Include instructions, delimiters AND cached result runs of complex fields.

    The depth carries across paragraph boundaries and supports nested fields.
    fldSimple is checked separately with its complete subtree.
    """
    depth, result = 0, []
    for run in root.iter(f"{{{W}}}r"):
        markers = list(run.iter(f"{{{W}}}fldChar"))
        instructions = list(run.iter(f"{{{W}}}instrText"))
        if depth or markers or instructions:
            result.append(run)
        for marker in markers:
            kind = marker.get(f"{{{W}}}fldCharType")
            if kind == "begin":
                depth += 1
            elif kind == "end":
                depth = max(0, depth - 1)
    return result


def inspect_preservation(source: bytes, exported: bytes, *, edits: list[dict],
                         reference_blocks: set[str], new_comments: list[str]) -> list[dict]:
    """Independent package inspection; does not call the document editing engine."""
    checks: list[dict] = []

    def check(identifier, passed, **evidence):
        checks.append(dict(id=identifier, passed=bool(passed), **evidence))

    before, after = parts(source), parts(exported)
    original, changed = xml(before[MAIN]), xml(after[MAIN])
    source_paras, result_paras = paragraphs(original), paragraphs(changed)
    comment_path = related_part(before, "comments")
    settings_path = related_part(before, "settings")
    allowed = {MAIN, comment_path, settings_path} - {None}
    changed_parts = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
    unexpected = sorted(set(changed_parts) - allowed)
    check("zip.part_inventory", set(before) == set(after), source_count=len(before),
          exported_count=len(after), missing=sorted(set(before) - set(after)), added=sorted(set(after) - set(before)))
    check("zip.untouched_parts_byte_identical", not unexpected,
          unchanged_count=sum(before.get(name) == after.get(name) for name in before),
          allowed_changes=sorted(allowed), changed_parts=changed_parts, unexpected_changes=unexpected)

    def same_objects(identifier, expression, minimum=1):
        old_nodes = original.xpath(expression, namespaces=NS)
        new_nodes = changed.xpath(expression, namespaces=NS)
        old, new = signatures(old_nodes), signatures(new_nodes)
        check(identifier, len(old) >= minimum and old == new, source_count=len(old), exported_count=len(new),
              source_signatures=old, exported_signatures=new)

    same_objects("structure.section_properties", ".//w:sectPr")
    same_objects("structure.paragraph_properties", ".//w:pPr")
    same_objects("structure.table_properties", ".//w:tblPr | .//w:tblGrid | .//w:trPr | .//w:tcPr")
    same_objects("objects.omml", ".//m:oMath | .//m:oMathPara")
    same_objects("objects.bookmarks", ".//w:bookmarkStart | .//w:bookmarkEnd")
    same_objects("objects.field_instructions", ".//w:instrText | .//w:fldChar | .//w:fldSimple")
    same_objects("objects.note_references", ".//w:footnoteReference | .//w:endnoteReference")
    old_fields, new_fields = signatures(field_runs(original)), signatures(field_runs(changed))
    check("objects.field_cached_runs", bool(old_fields) and old_fields == new_fields,
          source_count=len(old_fields), exported_count=len(new_fields),
          source_signatures=old_fields, exported_signatures=new_fields)
    for kind in ("footnotes", "endnotes"):
        path = related_part(before, kind)
        check(f"objects.{kind}_part", bool(path) and before.get(path) == after.get(path),
              part=path, source_sha256=digest(before[path]) if path in before else None,
              exported_sha256=digest(after[path]) if path in after else None)

    edited_indices = {int(edit["block_id"][1:]) for edit in edits}
    unedited = [index for index in range(len(source_paras)) if index not in edited_indices]
    divergent = [index for index in unedited if index >= len(result_paras)
                 or canonical(source_paras[index]) != canonical(result_paras[index])]
    check("structure.unedited_paragraphs", len(source_paras) == len(result_paras) and not divergent,
          checked_count=len(unedited), source_paragraphs=len(source_paras), exported_paragraphs=len(result_paras),
          divergent_blocks=[f"p{i}" for i in divergent])
    ref_indices = sorted(int(block[1:]) for block in reference_blocks)
    bad_refs = [index for index in ref_indices if index >= len(result_paras)
                or canonical(source_paras[index]) != canonical(result_paras[index])]
    check("objects.reference_paragraphs", bool(ref_indices) and not bad_refs,
          checked_blocks=sorted(reference_blocks), divergent_blocks=[f"p{i}" for i in bad_refs])

    revision_query = ".//w:ins | .//w:del | .//w:moveFrom | .//w:moveTo"
    old_revisions = {(node.tag, node.get(f"{{{W}}}id")): canonical(node)
                     for node in original.xpath(revision_query, namespaces=NS)}
    final_revision_nodes = changed.xpath(revision_query, namespaces=NS)
    result_revisions = {(node.tag, node.get(f"{{{W}}}id")): canonical(node) for node in final_revision_nodes}
    bad_revisions = [identifier for identifier, content in old_revisions.items()
                     if result_revisions.get(identifier) != content]
    check("objects.original_revisions", bool(old_revisions) and not bad_revisions,
          original_count=len(old_revisions), preserved_count=len(old_revisions) - len(bad_revisions),
          changed_ids=[list(item) for item in bad_revisions])

    source_comments = xml(before[comment_path]) if comment_path in before else None
    result_comments = xml(after[comment_path]) if comment_path in after else None
    old_comments = {node.get(f"{{{W}}}id"): canonical(node) for node in source_comments} if source_comments is not None else {}
    final_comments = {node.get(f"{{{W}}}id"): node for node in result_comments} if result_comments is not None else {}
    bad_comments = [identifier for identifier, content in old_comments.items()
                    if identifier not in final_comments or canonical(final_comments[identifier]) != content]
    check("objects.original_comments", bool(old_comments) and not bad_comments,
          original_count=len(old_comments), preserved_count=len(old_comments) - len(bad_comments), changed_ids=bad_comments)
    anchor_query = ".//w:commentRangeStart | .//w:commentRangeEnd | .//w:commentReference"
    def comment_anchors(root):
        return [[index, digest(canonical(node))] for index, paragraph in enumerate(paragraphs(root))
                for node in paragraph.xpath(anchor_query, namespaces=NS) if node.get(f"{{{W}}}id") in old_comments]
    old_anchors, final_anchors = comment_anchors(original), comment_anchors(changed)
    check("objects.original_comment_anchors", bool(old_anchors) and old_anchors == final_anchors,
          source_anchors=old_anchors, exported_anchors=final_anchors)
    added_comments = {identifier: node for identifier, node in final_comments.items() if identifier not in old_comments}
    def comment_text(comment):
        return "".join((node.text or "") if node.tag == f"{{{W}}}t" else "\t" if node.tag == f"{{{W}}}tab" else "\n"
                       for node in comment.iter() if node.tag in {f"{{{W}}}{tag}" for tag in ("t", "tab", "br", "cr")})
    added_text = [comment_text(node) for node in added_comments.values()]
    # Range/reference existence and order are checked independently of the comments part.
    anchor_failures = []
    document_order = {node: index for index, node in enumerate(changed.iter())}
    for identifier in added_comments:
        groups = [changed.xpath(f".//w:{tag}[@w:id=$id]", namespaces=NS, id=identifier)
                  for tag in ("commentRangeStart", "commentRangeEnd", "commentReference")]
        if any(len(group) != 1 for group in groups) or not (
            document_order[groups[0][0]] < document_order[groups[1][0]] < document_order[groups[2][0]]
        ):
            anchor_failures.append(identifier)
    check("changes.new_comment_valid", sorted(added_text) == sorted(new_comments) and not anchor_failures,
          expected_text=new_comments, actual_text=added_text, added_ids=sorted(added_comments), invalid_anchor_ids=anchor_failures)

    edit_evidence = []
    for edit in edits:
        index = int(edit["block_id"][1:])
        paragraph = result_paras[index]
        new_nodes = [node for node in paragraph.xpath(revision_query, namespaces=NS)
                     if (node.tag, node.get(f"{{{W}}}id")) not in old_revisions]
        deleted = "".join("".join(node.xpath(".//w:delText/text()", namespaces=NS)) for node in new_nodes
                          if node.tag == f"{{{W}}}del")
        inserted = "".join("".join(node.xpath(".//w:t/text()", namespaces=NS)) for node in new_nodes
                           if node.tag == f"{{{W}}}ins")
        metadata_valid = all(node.get(f"{{{W}}}id") and node.get(f"{{{W}}}author") and node.get(f"{{{W}}}date") for node in new_nodes)
        edit_evidence.append(dict(block_id=edit["block_id"], expected_deleted=edit["quote"], actual_deleted=deleted,
                                  expected_inserted=edit["replacement"], actual_inserted=inserted,
                                  revision_count=len(new_nodes), metadata_valid=bool(metadata_valid),
                                  passed=bool(new_nodes) and deleted == edit["quote"] and inserted == edit["replacement"] and bool(metadata_valid)))
    new_revision_nodes = [node for node in final_revision_nodes if (node.tag, node.get(f"{{{W}}}id")) not in old_revisions]
    identifiers = [node.get(f"{{{W}}}id") for node in new_revision_nodes]
    old_ids = {identifier for _, identifier in old_revisions}
    check("changes.new_revisions_valid", bool(edits) and all(item["passed"] for item in edit_evidence)
          and len(identifiers) == len(set(identifiers)) and not set(identifiers) & old_ids,
          edits=edit_evidence, new_ids=identifiers)
    if settings_path in before and settings_path in after:
        old_settings, new_settings = xml(before[settings_path]), xml(after[settings_path])
        tracking = new_settings.find(f"{{{W}}}trackRevisions")
        enabled = tracking is not None and tracking.get(f"{{{W}}}val", "true").lower() not in ("0", "false", "off")
        for node in (old_settings, new_settings):
            for child in list(node):
                if child.tag == f"{{{W}}}trackRevisions":
                    node.remove(child)
        check("changes.tracking_enabled_only_settings_change", enabled and canonical(old_settings) == canonical(new_settings),
              enabled=enabled, other_settings_preserved=canonical(old_settings) == canonical(new_settings))
    else:
        check("changes.tracking_enabled_only_settings_change", False, reason="Fixture must contain a settings part")
    return checks


def run_acceptance(source_path: Path, inventory_path: Path, output_dir: Path) -> dict:
    """Run real Flask endpoints, keeping the caller's project directory untouched."""
    source_path, inventory_path, output_dir = source_path.resolve(), inventory_path.resolve(), output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    audit = dict(schema="wencheng.acceptance.v1", started_at=datetime.now(timezone.utc).isoformat(),
                 passed=False, checks=[], steps=[], artifacts={},
                 scope="Deterministic HTTP workflow and OOXML structural preservation",
                 not_tested=["Microsoft Word pagination and visual rendering", "AI provider or prose quality", "All DOCX feature combinations"])

    def check(identifier, passed, **evidence):
        audit["checks"].append(dict(id=identifier, passed=bool(passed), **evidence))

    def artifact(name: str, content: bytes):
        path = output_dir / name
        path.write_bytes(content)
        audit["artifacts"][name] = dict(path=str(path), bytes=len(content), sha256=digest(content))

    try:
        source = source_path.read_bytes()
        inventory = json.loads(inventory_path.read_text(encoding="utf-8-sig"))
        cases = inventory["editable_cases"]
        if len(cases) < 2:
            raise ValueError("Fixture inventory needs at least body and table editing cases")
        artifact("source.docx", source)
        artifact("source-inventory.json", inventory_path.read_bytes())
        source_parts = parts(source)
        expected_hashes = inventory["preserve_parts"]
        check("fixture.inventory_part_hashes", bool(expected_hashes) and all(
            entry["part"] in source_parts and digest(source_parts[entry["part"]]) == entry["sha256"]
            for entry in expected_hashes), checked_parts=[entry["part"] for entry in expected_hashes])
        api = importlib.import_module("backend.app")
        from backend import store

        # Environment isolation is explicit; patch the already-imported module as well.
        with tempfile.TemporaryDirectory(prefix="wencheng-acceptance-", dir=output_dir) as isolated:
            data_dir = Path(isolated).resolve()
            with patch.dict(os.environ, {"WENCHENG_DATA": str(data_dir)}), patch.object(store, "DATA", data_dir):
                client = api.app.test_client()

                def request(method, path, label, **kwargs):
                    response = getattr(client, method)(path, **kwargs)
                    audit["steps"].append(dict(name=label, method=method.upper(), path=path, status=response.status_code))
                    if response.status_code != 200:
                        raise RuntimeError(f"{label}: HTTP {response.status_code}: {response.get_data(as_text=True)}")
                    return response

                def get_project(pid):
                    return request("get", f"/api/projects/{pid}", "read_project").get_json()

                def export(pid, label):
                    return request("get", f"/api/projects/{pid}/export", label).data

                project = request("post", "/api/projects/import", "import_source",
                                  data={"file": (BytesIO(source), source_path.name)}, content_type="multipart/form-data").get_json()
                pid = project["id"]
                initial_project = deepcopy(project)
                audit["source_project_id"] = pid
                pristine = export(pid, "export_without_changes")
                artifact("no-op-export.docx", pristine)
                check("workflow.no_op_export_byte_identical", pristine == source,
                      source_sha256=digest(source), exported_sha256=digest(pristine))

                protection_examples = {}
                for block in project["blocks"]:
                    for span in block["protected"]:
                        if span["end"] > span["start"]:
                            protection_examples.setdefault(span["kind"], (block, span))
                required_kinds = {"formula", "footnote", "endnote", "field", "references", "revision", "citation"}
                check("workflow.required_protections_detected", required_kinds <= protection_examples.keys(),
                      required=sorted(required_kinds), detected=sorted(protection_examples))
                reference_blocks = set()
                reference_evidence = []
                for entry in inventory["protected_objects"]["reference_entries"]:
                    matching = [block for block in project["blocks"] if block["text"] == entry]
                    covered = len(matching) == 1 and any(span["kind"] == "references" and span["start"] == 0
                        and span["end"] == len(entry) for span in matching[0]["protected"])
                    reference_evidence.append(dict(text=entry, found=len(matching), fully_protected=covered))
                    reference_blocks.update(block["id"] for block in matching)
                check("workflow.inventory_reference_protection", bool(reference_evidence)
                      and all(item["fully_protected"] for item in reference_evidence), entries=reference_evidence)
                probe_results = []
                for kind, (block, span) in sorted(protection_examples.items()):
                    response = client.post(f"/api/projects/{pid}/annotations", json=dict(
                        block_id=block["id"], start=span["start"], end=span["end"],
                        quote=block["text"][span["start"]:span["end"]], instruction="验收：受保护范围不应写入标记"))
                    probe_results.append(dict(kind=kind, block_id=block["id"], status=response.status_code,
                                              rejected=response.status_code == 400, error=(response.get_json() or {}).get("error")))
                after_probes = get_project(pid)
                check("workflow.protected_marking_rejected", bool(probe_results) and all(item["rejected"] for item in probe_results)
                      and after_probes["annotations"] == initial_project["annotations"]
                      and after_probes["version"] == initial_project["version"], probes=probe_results)

                edits = []
                for case in cases:
                    matching = [block for block in project["blocks"] if block["text"] == case["paragraph_text"]]
                    if len(matching) != 1:
                        raise ValueError(f"Fixture case {case['id']} must identify one exact paragraph, found {len(matching)}")
                    block = matching[0]
                    quote = case["quote"]
                    if not quote or block["text"].count(quote) != 1:
                        raise ValueError(f"Fixture case {case['id']} needs one nonempty exact quote")
                    start = block["text"].index(quote)
                    payload = dict(block_id=block["id"], start=start, end=start + len(quote), quote=quote,
                                   instruction=case["instruction"])
                    project = request("post", f"/api/projects/{pid}/annotations", "mark_" + case["id"], json=payload).get_json()
                    annotation = project["annotations"][-1]
                    edits.append(dict(case_id=case["id"], kind=block["kind"], annotation_id=annotation["id"],
                                      replacement=case["replacement"], expected_paragraph=case["expected_paragraph"], **payload))
                check("workflow.body_and_table_exact_marks", any(edit["kind"] == "paragraph" for edit in edits)
                      and any(edit["kind"] == "table-cell" for edit in edits), edits=edits)

                first = edits[0]
                project = request("post", f"/api/projects/{pid}/annotations/{first['annotation_id']}/comment", "write_word_comment", json={}).get_json()
                comment_snapshot = export(pid, "export_comment_snapshot")
                task_response = request("get", f"/api/projects/{pid}/tasks", "export_chat_tasks")
                artifact("tasks.json", task_response.data)
                tasks = task_response.get_json()
                check("workflow.tasks_keep_exact_anchors", len(tasks["tasks"]) == len(edits) and all(
                    any(task["id"] == edit["annotation_id"] and all(task[key] == edit[key] for key in ("block_id", "start", "end", "quote"))
                        for task in tasks["tasks"]) for edit in edits))
                results = dict(project_id=pid, results=[dict(id=edit["annotation_id"], quote=edit["quote"],
                    replacement=edit["replacement"], reason="验收固定建议：删去套话，保留论点、数字与引用。") for edit in edits])
                result_bytes = json.dumps(results, ensure_ascii=False, indent=2).encode("utf-8")
                artifact("suggestions.json", result_bytes)
                project = request("post", f"/api/projects/{pid}/tasks", "import_chat_suggestions",
                                  data={"file": (BytesIO(result_bytes), "suggestions.json")}, content_type="multipart/form-data").get_json()
                check("workflow.suggestions_wait_for_acceptance", all(item["status"] == "suggested" for item in project["annotations"])
                      and export(pid, "export_before_acceptance") == comment_snapshot)
                previous_bytes = None
                before_last_apply = None
                for edit in edits:
                    previous_bytes = export(pid, "capture_undo_checkpoint")
                    before_last_apply = deepcopy(project)
                    project = request("post", f"/api/projects/{pid}/annotations/{edit['annotation_id']}/apply",
                                      "apply_" + edit["case_id"], json={}).get_json()
                final_bytes = export(pid, "export_revised_document")
                artifact("exported.docx", final_bytes)
                artifact("project-after.json", json.dumps(project, ensure_ascii=False, indent=2).encode("utf-8"))
                visible = {block["id"]: block["text"] for block in project["blocks"]}
                check("workflow.accepted_text_exact", all(visible[edit["block_id"]] == edit["expected_paragraph"] for edit in edits)
                      and all(item["status"] == "applied" for item in project["annotations"]),
                      actual=[dict(block_id=edit["block_id"], text=visible[edit["block_id"]]) for edit in edits])
                audit["checks"].extend(inspect_preservation(source, final_bytes, edits=edits,
                    reference_blocks=reference_blocks, new_comments=[first["instruction"]]))
                check("workflow.immutable_original", (store.directory(pid) / "original.docx").read_bytes() == source)

                reimported = request("post", "/api/projects/import", "reimport_revised_document",
                    data={"file": (BytesIO(final_bytes), "reimported.docx")}, content_type="multipart/form-data").get_json()
                audit["reimport_project_id"] = reimported["id"]
                check("workflow.reimport_text_and_protection", reimported["blocks"] == project["blocks"]
                      and reimported["protections"] == project["protections"] and reimported["stats"] == project["stats"])
                check("workflow.reimport_export_byte_identical", export(reimported["id"], "export_reimported_document") == final_bytes)
                undone = request("post", f"/api/projects/{pid}/undo", "undo_last_acceptance", json={}).get_json()
                undone_bytes = export(pid, "export_after_undo")
                artifact("undone.docx", undone_bytes)
                check("workflow.undo_exact_snapshot", undone_bytes == previous_bytes
                      and undone["annotations"] == before_last_apply["annotations"]
                      and undone["history"] == before_last_apply["history"] and undone["version"] > project["version"],
                      expected_sha256=digest(previous_bytes), actual_sha256=digest(undone_bytes),
                      version_before=project["version"], version_after=undone["version"])
                check("workflow.storage_isolated", store.DATA == data_dir and os.environ["WENCHENG_DATA"] == str(data_dir))
    except Exception as exc:
        audit["error"] = f"{type(exc).__name__}: {exc}"
    audit["finished_at"] = datetime.now(timezone.utc).isoformat()
    audit["passed"] = bool(audit["checks"]) and all(item["passed"] for item in audit["checks"]) and "error" not in audit
    audit["summary"] = dict(passed_checks=sum(item["passed"] for item in audit["checks"]),
                            failed_count=sum(not item["passed"] for item in audit["checks"]),
                            failed_checks=[item["id"] for item in audit["checks"] if not item["passed"]])
    (output_dir / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "tests/fixtures/complex-academic.docx")
    parser.add_argument("--inventory", type=Path, default=ROOT / "tests/fixtures/complex-academic.inventory.json")
    parser.add_argument("--output", type=Path, default=ROOT / "acceptance/complex-paper")
    args = parser.parse_args()
    audit = run_acceptance(args.source, args.inventory, args.output)
    print(json.dumps(dict(passed=audit["passed"], **audit["summary"], error=audit.get("error"),
                          report=str(args.output.resolve() / "audit.json")), ensure_ascii=False, indent=2))
    return 0 if audit["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
