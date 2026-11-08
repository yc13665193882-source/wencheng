"""Run a real paper through the local HTTP app and independently audit its OOXML.

Cases are reviewable JSON: [{"block_id":"p12","quote":"...","replacement":"..."}].
Run with the bundled document Python runtime while the local app is running.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid

from acceptance_roundtrip import (W, NS, MAIN, canonical, digest, field_runs,
                                  paragraphs, parts, related_part, signatures, xml)


def prose_text(paragraph) -> str:
    """Read visible Word prose independently of the app's block/offset reader.

    Math, pictures and note markers have their own structural checks and are not
    converted into app-specific display placeholders here.
    """
    pieces = []
    ignored = {f'{{{W}}}{name}' for name in (
        'pPr', 'rPr', 'del', 'moveFrom', 'instrText', 'delInstrText', 'delText',
        'drawing', 'pict', 'object')}

    def visit(node):
        if node.tag in ignored or node.tag.startswith('{' + NS['m'] + '}'):
            return
        if node.tag == f'{{{W}}}p' and node is not paragraph:
            return
        if node.tag == f'{{{W}}}t':
            pieces.append(node.text or '')
        elif node.tag in {f'{{{W}}}tab', f'{{{W}}}ptab'}:
            pieces.append('\t')
        elif node.tag in {f'{{{W}}}br', f'{{{W}}}cr'}:
            pieces.append('\n')
        elif node.tag == f'{{{W}}}noBreakHyphen':
            pieces.append('\u2011')
        elif node.tag == f'{{{W}}}softHyphen':
            pieces.append('\u00ad')
        else:
            for child in node:
                visit(child)

    visit(paragraph)
    return ''.join(pieces)


def revision_view(root, existing_keys, *, accept):
    """Accept/reject only newly added text revisions on an in-memory XML copy."""
    view = deepcopy(root)
    for node in reversed(view.xpath('.//w:ins | .//w:del', namespaces=NS)):
        if (node.tag, node.get(f'{{{W}}}id')) in existing_keys:
            continue
        parent = node.getparent()
        keep = (node.tag == f'{{{W}}}ins') == accept
        if keep:
            for text in node.iter():
                if text.tag == f'{{{W}}}delText':
                    text.tag = f'{{{W}}}t'
                elif text.tag == f'{{{W}}}delInstrText':
                    text.tag = f'{{{W}}}instrText'
            index = parent.index(node)
            for child in list(node):
                parent.insert(index, child)
                index += 1
        parent.remove(node)
    return view


def audit_package(source: bytes, result: bytes, edits: list[dict],
                  expected_comments: list[dict]) -> list[dict]:
    before, after = parts(source), parts(result)
    old, new = xml(before[MAIN]), xml(after[MAIN])
    checks = []

    def check(name, passed, **evidence):
        checks.append(dict(id=name, passed=bool(passed), **evidence))

    comments_path = related_part(after, 'comments')
    allowed = {MAIN, comments_path, related_part(after, 'settings'),
               'word/_rels/document.xml.rels', '[Content_Types].xml'} - {None}
    changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
    check('package.parts_preserved', set(before) <= set(after), before=len(before), after=len(after))
    check('package.untouched_bytes', not (set(changed) - allowed), changed_parts=changed,
          identical_parts=sum(before.get(name) == after.get(name) for name in before))
    # New comment wiring may add a relation/content type; old entries must survive.
    for name in ['word/_rels/document.xml.rels', '[Content_Types].xml']:
        original, exported = xml(before[name]), xml(after[name])
        existing = signatures(list(original))
        final = signatures(list(exported))
        check('package.existing_' + name, all(item in final for item in existing), existing_count=len(existing))
    for name, expression in {
        'section_properties': './/w:sectPr', 'paragraph_properties': './/w:pPr',
        'table_properties': './/w:tblPr | .//w:tblGrid | .//w:trPr | .//w:tcPr',
        'formulas': './/m:oMath | .//m:oMathPara',
        'bookmarks': './/w:bookmarkStart | .//w:bookmarkEnd',
        'fields': './/w:instrText | .//w:fldChar | .//w:fldSimple',
        'note_references': './/w:footnoteReference | .//w:endnoteReference',
        'drawings': './/w:drawing | .//w:pict',
    }.items():
        a, b = old.xpath(expression, namespaces=NS), new.xpath(expression, namespaces=NS)
        check('objects.' + name, signatures(a) == signatures(b), original_count=len(a), final_count=len(b), present=bool(a))
    check('objects.field_cached_runs', signatures(field_runs(old)) == signatures(field_runs(new)), original_count=len(field_runs(old)))
    for kind in ['footnotes', 'endnotes']:
        name = related_part(before, kind)
        check('objects.' + kind, name is None or before[name] == after.get(name), present=name is not None)
    edited_indices = {int(edit['block_id'][1:]) for edit in edits}
    a, b = paragraphs(old), paragraphs(new)
    different = [f'p{i}' for i, node in enumerate(a) if i not in edited_indices and (i >= len(b) or canonical(node) != canonical(b[i]))]
    check('objects.unedited_paragraphs', len(a) == len(b) and not different,
          original_count=len(a), final_count=len(b), changed_unexpectedly=different)
    query = ' | '.join('.//w:' + name for name in (
        'ins', 'del', 'moveFrom', 'moveTo', 'rPrChange', 'pPrChange',
        'tblPrChange', 'trPrChange', 'tcPrChange', 'sectPrChange'))
    original_revisions = {(n.tag, n.get(f'{{{W}}}id')): canonical(n) for n in old.xpath(query, namespaces=NS)}
    final_revisions = {(n.tag, n.get(f'{{{W}}}id')): canonical(n) for n in new.xpath(query, namespaces=NS)}
    check('objects.existing_revisions', all(final_revisions.get(key) == value for key, value in original_revisions.items()), original_count=len(original_revisions))
    old_comments_path = related_part(before, 'comments')
    old_comments = {n.get(f'{{{W}}}id'): canonical(n) for n in xml(before[old_comments_path])} if old_comments_path else {}
    new_comments = {n.get(f'{{{W}}}id'): n for n in xml(after[comments_path])} if comments_path else {}
    check('objects.existing_comments', all(key in new_comments and canonical(new_comments[key]) == value for key, value in old_comments.items()), original_count=len(old_comments))
    anchors = './/w:commentRangeStart | .//w:commentRangeEnd | .//w:commentReference'
    def original_anchors(root):
        return [(i, digest(canonical(n))) for i, p in enumerate(paragraphs(root)) for n in p.xpath(anchors, namespaces=NS) if n.get(f'{{{W}}}id') in old_comments]
    check('objects.existing_comment_anchors', original_anchors(old) == original_anchors(new))
    added_comments = set(new_comments) - set(old_comments)
    order = {node: i for i, node in enumerate(new.iter())}
    valid_comments = []
    for key in added_comments:
        groups = [new.xpath(f'.//w:{tag}[@w:id=$id]', namespaces=NS, id=key) for tag in ('commentRangeStart', 'commentRangeEnd', 'commentReference')]
        valid_comments.append(all(len(group) == 1 for group in groups) and order[groups[0][0]] < order[groups[1][0]] < order[groups[2][0]])
    check('changes.new_comment_anchors', len(added_comments) == len(expected_comments) and all(valid_comments), added_ids=sorted(added_comments))
    actual_comments = []
    for key in sorted(added_comments):
        comment = new_comments[key]
        text = '\n'.join(prose_text(p) for p in comment.findall(f'{{{W}}}p'))
        locations = [f'p{i}' for i, p in enumerate(b)
                     if p.xpath('.//w:commentRangeStart[@w:id=$id]', namespaces=NS, id=key)]
        actual_comments.append(dict(text=text, blocks=locations))
    wanted_comments = [dict(text=c['text'], blocks=[c['block_id']]) for c in expected_comments]
    check('changes.new_comment_text_and_location',
          sorted(actual_comments, key=str) == sorted(wanted_comments, key=str),
          expected=wanted_comments, actual=actual_comments)
    added_revisions = [node for node in new.xpath(query, namespaces=NS) if (node.tag, node.get(f'{{{W}}}id')) not in original_revisions]
    ids = [node.get(f'{{{W}}}id') for node in added_revisions]
    old_ids = {key[1] for key in original_revisions}
    revision_blocks = {f'p{i}' for i, p in enumerate(b) for node in p.xpath(query, namespaces=NS)
                       if (node.tag, node.get(f'{{{W}}}id')) not in original_revisions}
    check('changes.revision_metadata', bool(ids) and len(ids) == len(set(ids))
          and not (set(ids) & old_ids)
          and all(node.get(f'{{{W}}}author') and node.get(f'{{{W}}}date') for node in added_revisions), added_count=len(ids))
    check('changes.revision_types_and_locations',
          all(node.tag in {f'{{{W}}}ins', f'{{{W}}}del'} for node in added_revisions)
          and revision_blocks == {e['block_id'] for e in edits},
          actual_blocks=sorted(revision_blocks))
    # Accepting only the new revisions must yield exactly the intended visible text,
    # while existing revisions remain covered by their own semantic comparison.
    original_text = [prose_text(p) for p in a]
    expected_text = list(original_text)
    anchor_evidence = []
    for edit in edits:
        index = int(edit['block_id'][1:])
        quote = edit['quote']
        matches = original_text[index].count(quote) if quote else 0
        anchor_evidence.append(dict(block_id=edit['block_id'], quote=quote, matches=matches))
        if matches == 1:
            expected_text[index] = expected_text[index].replace(quote, edit['replacement'], 1)
    check('changes.independent_source_anchors', bool(edits) and all(e['matches'] == 1 for e in anchor_evidence), anchors=anchor_evidence)
    accepted_text = [prose_text(p) for p in paragraphs(revision_view(new, original_revisions, accept=True))]
    rejected_text = [prose_text(p) for p in paragraphs(revision_view(new, original_revisions, accept=False))]
    check('changes.accepted_new_revisions_text', accepted_text == expected_text,
          checked_paragraphs=len(expected_text),
          divergent_blocks=[f'p{i}' for i, text in enumerate(expected_text)
                            if i >= len(accepted_text) or accepted_text[i] != text])
    check('changes.rejected_new_revisions_text', rejected_text == original_text,
          checked_paragraphs=len(original_text),
          divergent_blocks=[f'p{i}' for i, text in enumerate(original_text)
                            if i >= len(rejected_text) or rejected_text[i] != text])
    settings_path = related_part(after, 'settings')
    if settings_path and settings_path in before:
        original_settings, final_settings = xml(before[settings_path]), xml(after[settings_path])
        tracking = final_settings.find(f'{{{W}}}trackRevisions')
        enabled = tracking is not None and tracking.get(f'{{{W}}}val', 'true').lower() not in ('0', 'false', 'off')
        for settings in (original_settings, final_settings):
            for node in list(settings):
                if node.tag == f'{{{W}}}trackRevisions':
                    settings.remove(node)
        check('changes.tracking_only_settings_change', enabled and canonical(original_settings) == canonical(final_settings), enabled=enabled)
    else:
        check('changes.tracking_only_settings_change', False, reason='Source settings part missing; needs a separate explicit expectation.')
    return checks


def run(source_path: Path, cases_path: Path, output: Path, base: str):
    output.mkdir(parents=True, exist_ok=True)
    source = source_path.read_bytes()
    cases = json.loads(cases_path.read_text('utf-8-sig'))
    audit = dict(schema='wencheng.real-paper.v1', started_at=datetime.now(timezone.utc).isoformat(), checks=[], steps=[])

    def check(name, passed, **evidence):
        audit['checks'].append(dict(id=name, passed=bool(passed), **evidence))

    def save(name, value):
        data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')
        (output / name).write_bytes(data)

    def call(method, endpoint, payload=None, file=None, raw=False, expect=200):
        headers, data = {}, None
        if file:
            name, content = file
            boundary = 'wc-' + uuid.uuid4().hex
            data = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + content + f'\r\n--{boundary}--\r\n'.encode())
            headers['Content-Type'] = 'multipart/form-data; boundary=' + boundary
        elif payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        started = time.perf_counter()
        try:
            response = urlopen(Request(base + endpoint, data=data, headers=headers, method=method), timeout=180)
        except HTTPError as error:
            response = error
        content = response.read()
        audit['steps'].append(dict(method=method, endpoint=endpoint, status=response.status, seconds=round(time.perf_counter()-started, 4)))
        if response.status != expect:
            raise RuntimeError(f'{method} {endpoint}: {response.status}: {content.decode("utf-8", errors="replace")[:500]}')
        return content if raw else json.loads(content)

    try:
        if not isinstance(cases, list) or not cases or len({c['block_id'] for c in cases}) != len(cases):
            raise ValueError('Acceptance cases must be a nonempty list with one edit per block.')
        check('workflow.case_source_hash', all(c.get('source_sha256', digest(source)) == digest(source) for c in cases))
        save('source.docx', source)
        project = call('POST', '/api/projects/import', file=('real-paper-' + output.name + '.docx', source))
        pid = project['id']
        audit['project_id'] = pid
        audit['initial_stats'] = project['stats']
        save('project-before.json', project)
        exported = call('GET', f'/api/projects/{pid}/export', raw=True)
        save('no-op-export.docx', exported)
        check('workflow.no_op_bytes', source == exported)
        # Probe one actual nonempty protected range of each kind present in this paper.
        protected = {}
        for block in project['blocks']:
            for region in block.get('protected', []):
                if region['end'] > region['start']:
                    protected.setdefault(region['kind'], (block, region))
        probes = []
        for kind, (block, region) in protected.items():
            body = dict(block_id=block['id'], start=region['start'], end=region['end'], quote=block['text'][region['start']:region['end']], instruction='验收保护区，不应创建标记')
            call('POST', f'/api/projects/{pid}/annotations', body, expect=400)
            probes.append(kind)
        check('workflow.protection_rejected', bool(probes), kinds=probes)
        edits = []
        for case in cases:
            block = next(b for b in project['blocks'] if b['id'] == case['block_id'])
            start = case['start'] if 'start' in case else block['text'].index(case['quote'])
            if not case['quote'] or block['text'][start:start+len(case['quote'])] != case['quote']:
                raise ValueError(f'Case quote does not match {case["block_id"]} at its expected offset.')
            edit = dict(case, start=start, end=start+len(case['quote']))
            edit.setdefault('instruction', '验收用局部表达调整，保留论点、数字、引文和正式文风。')
            edit['expected_paragraph'] = block['text'][:start] + edit['replacement'] + block['text'][edit['end']:]
            project = call('POST', f'/api/projects/{pid}/annotations', {key:edit[key] for key in ('block_id','start','end','quote','instruction')})
            edit['annotation_id'] = project['annotations'][-1]['id']
            edits.append(edit)
        save('edits.json', edits)
        first = edits[0]
        project = call('POST', f'/api/projects/{pid}/annotations/{first["annotation_id"]}/comment', {})
        comment_snapshot = call('GET', f'/api/projects/{pid}/export', raw=True)
        tasks = call('GET', f'/api/projects/{pid}/tasks')
        save('tasks.json', tasks)
        check('workflow.task_anchors', len(tasks['tasks']) == len(edits) and all(any(task['id'] == edit['annotation_id'] and all(task[k] == edit[k] for k in ('block_id','start','end','quote')) for task in tasks['tasks']) for edit in edits))
        suggestions = dict(project_id=pid, results=[dict(id=e['annotation_id'], quote=e['quote'], replacement=e['replacement'], reason='真实论文往返验收固定改稿') for e in edits])
        save('suggestions.json', suggestions)
        project = call('POST', f'/api/projects/{pid}/tasks', suggestions)
        check('workflow.suggestions_do_not_apply', call('GET', f'/api/projects/{pid}/export', raw=True) == comment_snapshot)
        for edit in edits:
            checkpoint = call('GET', f'/api/projects/{pid}/export', raw=True)
            project = call('POST', f'/api/projects/{pid}/annotations/{edit["annotation_id"]}/apply', {})
        call('POST', f'/api/projects/{pid}/undo', {})
        check('workflow.undo_bytes', call('GET', f'/api/projects/{pid}/export', raw=True) == checkpoint)
        project = call('POST', f'/api/projects/{pid}/annotations/{edits[-1]["annotation_id"]}/apply', {})
        final = call('GET', f'/api/projects/{pid}/export', raw=True)
        save('exported.docx', final)
        save('project-after.json', project)
        expected = {e['block_id']: e['expected_paragraph'] for e in edits}
        actual = {b['id']:b['text'] for b in project['blocks'] if b['id'] in expected}
        check('workflow.expected_text', actual == expected)
        audit['checks'].extend(audit_package(source, final, edits,
                                           [dict(block_id=first['block_id'], text=first['instruction'])]))
        reimported = call('POST', '/api/projects/import', file=('reimport-' + output.name + '.docx', final))
        audit['reimport_project_id'] = reimported['id']
        check('workflow.reimport_blocks', reimported['blocks'] == project['blocks'])
        check('workflow.reimport_bytes', call('GET', f'/api/projects/{reimported["id"]}/export', raw=True) == final)
        audit['hashes'] = dict(source=digest(source), exported=digest(final))
    except Exception as error:
        audit['error'] = f'{type(error).__name__}: {error}'
    audit['finished_at'] = datetime.now(timezone.utc).isoformat()
    audit['passed'] = bool(audit['checks']) and all(c['passed'] for c in audit['checks']) and 'error' not in audit
    audit['summary'] = dict(passed=sum(c['passed'] for c in audit['checks']), total=len(audit['checks']), failures=[c['id'] for c in audit['checks'] if not c['passed']])
    save('audit.json', audit)
    return audit


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base', default='http://127.0.0.1:8765')
    args = parser.parse_args()
    result = run(args.source, args.cases, args.output, args.base)
    print(json.dumps({key:result.get(key) for key in ('passed','summary','project_id','error')}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
