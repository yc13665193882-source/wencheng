"""HTTP integration checks; all model responses are local deterministic mocks."""
from __future__ import annotations

from io import BytesIO
import importlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
api = importlib.import_module("backend.app")
from backend import store, docx_engine
from scripts.create_fixture import build_fixture


def parts(data):
    with ZipFile(BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


class AppIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = build_fixture()
        cls.test_output = (ROOT / "test-output").resolve()
        cls.test_output.mkdir(exist_ok=True)

    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="app-test-", dir=self.test_output)).resolve()
        self.data_patch = patch.object(store, "DATA", self.data)
        self.data_patch.start()
        self.client = api.app.test_client()
        with api.jobs_lock:
            api.jobs.clear()

    def tearDown(self):
        self.data_patch.stop()
        # This directory is created by this test and must remain inside test-output.
        target = self.data.resolve()
        if target.parent != self.test_output or not target.name.startswith("app-test-"):
            raise AssertionError("Refusing cleanup outside this test's directory")
        shutil.rmtree(target)

    def ok(self, response):
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def create(self, paragraphs):
        return self.ok(self.client.post("/api/projects", json={"title": "集成测试", "paragraphs": paragraphs}))

    def test_health_uses_runtime_version_file_without_node_package(self):
        (self.data / 'VERSION').write_text('2.4.0-rc.3\n', encoding='utf-8')
        with patch.object(store, 'ROOT', self.data):
            self.assertEqual(self.ok(self.client.get('/api/health'))['version'], '2.4.0-rc.3')
            # The runtime release marker takes precedence if package metadata is also present.
            (self.data / 'package.json').write_text('{"version":"0.0.0"}', encoding='utf-8')
            self.assertEqual(self.ok(self.client.get('/api/health'))['version'], '2.4.0-rc.3')

    def test_health_reads_source_package_version_and_does_not_invent_a_missing_version(self):
        package = self.data / 'package.json'
        package.write_text('{"version":"3.1.0-rc.2"}', encoding='utf-8')
        with patch.object(store, 'ROOT', self.data):
            self.assertEqual(self.ok(self.client.get('/api/health'))['version'], '3.1.0-rc.2')
            package.unlink()
            response = self.client.get('/api/health')
            self.assertNotEqual(response.status_code, 200)
            self.assertNotIn('version', response.get_json())

    def test_nonlocal_host_cannot_read_or_modify_local_projects(self):
        project = self.create(['Private local text'])
        for host in ('rebind.example:8765', '127.0.0.1.attacker.example:8765'):
            with self.subTest(host=host):
                response = self.client.get('/api/projects', base_url='http://' + host)
                self.assertEqual(response.status_code, 400)
                self.assertNotIn(project['title'], response.get_data(as_text=True))
                response = self.client.post('/api/projects', base_url='http://' + host,
                                            json={'title': 'Must not be created', 'paragraphs': []})
                self.assertEqual(response.status_code, 400)
        self.assertEqual(len(store.list_projects()), 1)

    def test_local_hosts_and_development_origin_remain_usable(self):
        for host in ('127.0.0.1:8765', 'localhost:8765', '[::1]:8765', 'localhost:5173'):
            with self.subTest(host=host):
                response = self.client.get('/api/health', base_url='http://' + host)
                self.assertEqual(response.status_code, 200)
        response = self.client.post('/api/projects', base_url='http://127.0.0.1:8765',
                                    headers={'Origin': 'http://localhost:5173'},
                                    json={'title': 'Local development', 'paragraphs': []})
        self.assertEqual(response.status_code, 200)

    def imported(self):
        return self.ok(self.client.post("/api/projects/import", data={"file": (BytesIO(self.fixture), "academic.docx")},
                                        content_type="multipart/form-data"))

    def get(self, pid):
        return self.ok(self.client.get(f"/api/projects/{pid}"))

    def mark(self, project, block_id, start, end, instruction="精简表达"):
        block = next(b for b in project["blocks"] if b["id"] == block_id)
        new = self.ok(self.client.post(f"/api/projects/{project['id']}/annotations", json={
            "block_id": block_id, "start": start, "end": end,
            "quote": block["text"][start:end], "instruction": instruction,
        }))
        return new, new["annotations"][-1]

    def supply(self, project, replacements):
        result = {"project_id": project["id"], "results": [
            {"id": annotation["id"], "quote": annotation["quote"], "replacement": text, "reason": "删除重复铺垫"}
            for annotation, text in replacements
        ]}
        return self.ok(self.client.post(f"/api/projects/{project['id']}/tasks", json=result))

    def apply(self, project, annotation):
        return self.ok(self.client.post(f"/api/projects/{project['id']}/annotations/{annotation['id']}/apply"))

    def wait_job(self, jid, timeout=4):
        limit = time.monotonic() + timeout
        while time.monotonic() < limit:
            job = self.ok(self.client.get(f"/api/jobs/{jid}"))
            if job["status"] != "running":
                return job
            time.sleep(.02)
        self.fail("Mock AI job did not finish")

    def test_import_mark_chat_results_revision_export_and_undo(self):
        project = self.imported()
        initial = store.document(project["id"])
        old_text = project["blocks"][1]["text"]
        start = old_text.index("需要强调的是", 6)
        project, annotation = self.mark(project, "p1", start, start + len("需要强调的是，"))
        task_response = self.client.get(f"/api/projects/{project['id']}/tasks")
        self.assertEqual(task_response.status_code, 200)
        tasks = json.loads(task_response.data)
        self.assertEqual(tasks["schema"], "wencheng.tasks.v1")
        self.assertEqual(tasks["tasks"][0]["context"], old_text)
        self.assertEqual(tasks["tasks"][0]["id"], annotation["id"])
        result = {"project_id": project["id"], "results": [{"id": annotation["id"], "quote": annotation["quote"],
                  "replacement": "", "reason": "去掉重复强调"}]}
        project = self.ok(self.client.post(f"/api/projects/{project['id']}/tasks", data={
            "file": (BytesIO(json.dumps(result, ensure_ascii=False).encode("utf-8-sig")), "results.json")
        }, content_type="multipart/form-data"))
        self.assertEqual(project["annotations"][0]["status"], "suggested")
        project = self.apply(project, annotation)
        self.assertEqual(project["annotations"][0]["status"], "applied")
        self.assertEqual(project["blocks"][1]["text"], "需要强调的是，本研究结果支持上述判断。")
        export = self.client.get(f"/api/projects/{project['id']}/export")
        self.assertEqual(export.status_code, 200)
        edited = parts(export.data)
        original = parts(initial)
        xml = etree.fromstring(edited["word/document.xml"])
        self.assertTrue(xml.findall(".//w:del", docx_engine.NS))
        self.assertEqual(edited["word/comments.xml"], original["word/comments.xml"])
        self.assertEqual(edited["word/footnotes.xml"], original["word/footnotes.xml"])
        self.assertEqual((store.directory(project["id"]) / "original.docx").read_bytes(), initial)
        project = self.ok(self.client.post(f"/api/projects/{project['id']}/undo"))
        self.assertEqual(project["blocks"][1]["text"], old_text)
        self.assertEqual(project["annotations"][0]["status"], "suggested")
        self.assertEqual(store.document(project["id"]), initial)

    def test_repeated_text_and_later_annotation_offsets(self):
        project = self.create(["alpha target beta target omega"])
        text = project["blocks"][1]["text"]
        project, first = self.mark(project, "p1", 0, 5)
        start = text.rindex("target")
        project, later = self.mark(project, "p1", start, start + len("target"))
        project = self.supply(project, [(first, "A"), (later, "result")])
        project = self.apply(project, first)
        moved = next(a for a in project["annotations"] if a["id"] == later["id"])
        self.assertEqual(moved["start"], start - 4)
        self.assertEqual(moved["end"], start + 2)
        self.assertEqual(moved["status"], "suggested")
        project = self.apply(project, moved)
        self.assertEqual(project["blocks"][1]["text"], "A target beta result omega")
        xml = etree.fromstring(parts(store.document(project["id"]))["word/document.xml"])
        self.assertEqual(len(xml.findall(".//w:ins", docx_engine.NS)), 2)

    def test_overlapping_annotation_becomes_conflict(self):
        project = self.create(["one overlapping phrase remains"])
        project, first = self.mark(project, "p1", 4, 15)
        project, overlap = self.mark(project, "p1", 4, 22)
        project = self.supply(project, [(first, "short"), (overlap, "alternative")])
        project = self.apply(project, first)
        self.assertEqual(next(a for a in project["annotations"] if a["id"] == overlap["id"])["status"], "conflict")
        response = self.client.post(f"/api/projects/{project['id']}/annotations/{overlap['id']}/apply")
        self.assertEqual(response.status_code, 400)

    def test_applied_and_mismatched_results_are_rejected(self):
        project = self.create(["word to revise"])
        project, annotation = self.mark(project, "p1", 0, 4)
        bad = {"project_id": project["id"], "results": [{"id": annotation["id"], "quote": "wrong", "replacement": "term"}]}
        response = self.client.post(f"/api/projects/{project['id']}/tasks", json=bad)
        self.assertEqual(response.status_code, 400)
        project = self.supply(project, [(annotation, "term")])
        project = self.apply(project, annotation)
        old = {"project_id": project["id"], "results": [{"id": annotation["id"], "quote": "word", "replacement": "old suggestion"}]}
        version = project["version"]
        response = self.client.post(f"/api/projects/{project['id']}/tasks", json=old)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.get(project["id"])["version"], version)

    def test_results_batch_validation_is_atomic(self):
        project = self.create(["first second"])
        project, first = self.mark(project, "p1", 0, 5)
        project, second = self.mark(project, "p1", 6, 12)
        response = self.client.post(f"/api/projects/{project['id']}/tasks", json={"project_id": project["id"], "results": [
            {"id": first["id"], "quote": "first", "replacement": "one"},
            {"id": second["id"], "quote": "stale", "replacement": "two"},
        ]})
        self.assertEqual(response.status_code, 400)
        unchanged = self.get(project["id"])
        self.assertEqual(unchanged["version"], project["version"])
        self.assertEqual([a["status"] for a in unchanged["annotations"]], ["pending", "pending"])

    def test_formal_comments_preserve_original_comment(self):
        project = self.imported()
        project, annotation = self.mark(project, "p2", 5, 18, "请简化此处措辞")
        project = self.ok(self.client.post(f"/api/projects/{project['id']}/annotations/{annotation['id']}/comment"))
        self.assertEqual(project["stats"]["comments"], 2)
        comments = etree.fromstring(parts(store.document(project["id"]))["word/comments.xml"])
        old = etree.fromstring(parts(self.fixture)["word/comments.xml"])[0]
        self.assertEqual(etree.tostring(old), etree.tostring(comments[0]))
        self.assertIn("请简化此处措辞", "".join(comments[1].itertext()))
        duplicate = self.client.post(f"/api/projects/{project['id']}/annotations/{annotation['id']}/comment")
        self.assertEqual(duplicate.status_code, 400)

    def test_protected_formula_field_citation_and_footnote_rejected(self):
        project = self.imported()
        checked = set()
        for block in project["blocks"]:
            for region in block["protected"]:
                if region["kind"] not in {"formula", "field", "citation", "footnote", "references"} or region["end"] <= region["start"]:
                    continue
                a, b = region["start"], region["end"]
                response = self.client.post(f"/api/projects/{project['id']}/annotations", json={
                    "block_id": block["id"], "start": a, "end": b, "quote": block["text"][a:b], "instruction": "修改"
                })
                self.assertEqual(response.status_code, 400, region["kind"])
                checked.add(region["kind"])
        self.assertEqual(checked, {"formula", "field", "citation", "footnote", "references"})
        self.assertEqual(self.get(project["id"])["annotations"], [])

    def test_boolean_offsets_are_rejected_before_creating_an_unusable_mark(self):
        project = self.create(["word"])
        for start, end in ((False, 1), (0, True), (True, 2)):
            with self.subTest(start=start, end=end):
                response = self.client.post(f"/api/projects/{project['id']}/annotations", json={
                    "block_id": "p1", "start": start, "end": end, "quote": "word"[start:end], "instruction": "精简"
                })
                self.assertEqual(response.status_code, 400)
        unchanged = self.get(project["id"])
        self.assertEqual(unchanged["annotations"], [])
        self.assertEqual(unchanged["version"], project["version"])

    def test_http_protection_matches_engine_at_invisible_boundaries_and_page_breaks(self):
        def node(tag, text=None, **attrs):
            result = etree.Element(f"{{{docx_engine.W}}}{tag}",
                {f"{{{docx_engine.W}}}{key}": str(value) for key, value in attrs.items()})
            result.text = text
            return result

        def text_run(text):
            result = node("r")
            result.append(node("t", text))
            return result

        for kind in ("bookmark", "comment", "revision", "field", "layout"):
            with self.subTest(kind=kind):
                data = docx_engine.create_document("", ["leftright"])
                if kind == "comment":
                    data = docx_engine.add_comment(data, "p0", 4, 9, "right", "Original comment")
                else:
                    _, root = docx_engine._package(data)
                    paragraph = root.find("w:body/w:p", docx_engine.NS)
                    for child in list(paragraph):
                        paragraph.remove(child)
                    paragraph.append(text_run("left"))
                    if kind == "bookmark":
                        paragraph.append(node("bookmarkStart", id=20, name="Target"))
                    elif kind == "revision":
                        deletion = node("del", id=20, author="Original author")
                        run = node("r")
                        run.append(node("delText", "removed"))
                        deletion.append(run)
                        paragraph.append(deletion)
                    elif kind == "field":
                        paragraph.append(node("fldSimple", instr=" REF missing "))
                    else:
                        run = node("r")
                        run.append(node("br", type="page"))
                        paragraph.append(run)
                    paragraph.append(text_run("right"))
                    if kind == "bookmark":
                        paragraph.append(node("bookmarkEnd", id=20))
                    data = docx_engine._repack(data, {docx_engine.MAIN: docx_engine._serialize(root)})
                project = self.ok(self.client.post("/api/projects/import", data={"file": (BytesIO(data), "boundaries.docx")},
                    content_type="multipart/form-data"))
                block = project["blocks"][0]
                self.assertTrue(any(region["kind"] == kind for region in block["protected"]))
                response = self.client.post(f"/api/projects/{project['id']}/annotations", json={
                    "block_id": "p0", "start": 0, "end": len(block["text"]), "quote": block["text"], "instruction": "合并文字"
                })
                self.assertEqual(response.status_code, 400)
                start = block["text"].index("right")
                project, annotation = self.mark(project, "p0", start, start + 5)
                project = self.supply(project, [(annotation, "after")])
                project = self.apply(project, annotation)
                self.assertEqual(project["blocks"][0]["text"], block["text"].replace("right", "after"))

    def test_cross_origin_mutation_rejected(self):
        response = self.client.post("/api/projects", json={"title": "外部页面"}, headers={"Origin": "https://example.org"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.ok(self.client.get("/api/projects"))["projects"], [])
        response = self.client.post("/api/projects", json={"title": "本地页面"}, headers={"Origin": "http://localhost:5173"})
        self.assertEqual(response.status_code, 200)

    def test_generated_paragraph_visible_before_job_completion(self):
        project = self.create([])
        first_saved, release = threading.Event(), threading.Event()

        def fake_generate(*args, **kwargs):
            yield "第一段已经完成。"
            first_saved.set()
            if not release.wait(4):
                raise RuntimeError("test gate timed out")
            yield "Second paragraph is complete."

        with patch.object(api.ai, "generate", side_effect=fake_generate):
            jid = self.ok(self.client.post(f"/api/projects/{project['id']}/generate", json={"prompt": "写两段"}))["job_id"]
            try:
                self.assertTrue(first_saved.wait(3), "first paragraph was not saved")
                running = self.ok(self.client.get(f"/api/jobs/{jid}"))
                self.assertEqual(running["status"], "running")
                self.assertEqual(running["progress"], 1)
                visible = self.get(project["id"])
                self.assertIn("第一段已经完成。", [b["text"] for b in visible["blocks"]])
                self.assertNotIn("Second paragraph is complete.", [b["text"] for b in visible["blocks"]])
                self.assertEqual(self.client.post(f"/api/projects/{project['id']}/undo").status_code, 400)
                self.assertEqual(self.client.post(f"/api/projects/{project['id']}/generate", json={"prompt": "重复启动"}).status_code, 400)
            finally:
                release.set()
                finished = self.wait_job(jid)
            self.assertEqual(finished["status"], "done")
            self.assertEqual(finished["progress"], 2)
            self.assertEqual(self.get(project["id"])["blocks"][-1]["text"], "Second paragraph is complete.")

    def test_generation_failure_keeps_completed_paragraph(self):
        project = self.create([])

        def fake_generate(*args, **kwargs):
            yield "已完成的段落。"
            raise RuntimeError("mock model failure")

        with patch.object(api.ai, "generate", side_effect=fake_generate):
            jid = self.ok(self.client.post(f"/api/projects/{project['id']}/generate", json={"prompt": "写作"}))["job_id"]
            finished = self.wait_job(jid)
        self.assertEqual(finished["status"], "error")
        self.assertEqual(finished["progress"], 1)
        self.assertIn("mock model failure", finished["error"])
        self.assertEqual(self.get(project["id"])["blocks"][-1]["text"], "已完成的段落。")

    def test_sidebar_rewrite_shares_same_annotation(self):
        project = self.create(["需要强调的是，结果稳定。"])
        project, annotation = self.mark(project, "p1", 0, 7)
        with patch.object(api.ai, "rewrite", return_value={"replacement": "", "reason": "去掉强调"}) as model:
            project = self.ok(self.client.post(f"/api/projects/{project['id']}/annotations/{annotation['id']}/suggest"))
        self.assertEqual(model.call_count, 1)
        self.assertEqual(project["annotations"][0]["id"], annotation["id"])
        self.assertEqual(project["annotations"][0]["status"], "suggested")
        self.assertEqual(project["blocks"][1]["text"], "需要强调的是，结果稳定。")
        project = self.apply(project, annotation)
        self.assertEqual(project["blocks"][1]["text"], "结果稳定。")


if __name__ == "__main__":
    unittest.main()
