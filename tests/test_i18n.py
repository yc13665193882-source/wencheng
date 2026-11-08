"""Language switching is presentation-only, including asynchronous job errors."""
from __future__ import annotations

import ast
import importlib
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
api = importlib.import_module('backend.app')
from backend import ai, docx_engine, i18n, rules, store
from scripts.create_fixture import build_fixture

EN = {'Accept-Language': 'en-US,en;q=0.9'}
ZH = {'Accept-Language': 'zh-CN'}


class LocalizationTests(unittest.TestCase):
    def setUp(self):
        self.output = ROOT / 'test-output'
        self.output.mkdir(exist_ok=True)
        self.data = Path(tempfile.mkdtemp(prefix='i18n-', dir=self.output))
        self.data_patch = patch.object(store, 'DATA', self.data)
        self.data_patch.start()
        self.client = api.app.test_client()
        with api.jobs_lock:
            api.jobs.clear()

    def tearDown(self):
        self.data_patch.stop()
        if self.data.resolve().parent != self.output.resolve():
            raise AssertionError('Unexpected test directory')
        shutil.rmtree(self.data)

    def ok(self, response):
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def create(self, paragraphs=None):
        return self.ok(self.client.post('/api/projects', json={
            'title': '用户标题：保留中文',
            'paragraphs': paragraphs or ['需要强调的是，测得均值为 0.24，结果可能受温度影响 [1]。'],
        }))

    def get(self, pid, headers=EN):
        return self.ok(self.client.get(f'/api/projects/{pid}', headers=headers))

    def wait_job(self, jid):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            value = self.ok(self.client.get(f'/api/jobs/{jid}', headers=EN))
            if value['status'] != 'running':
                return value
            time.sleep(.01)
        self.fail('Mock job did not finish')

    def test_language_quality_and_defaults(self):
        for header, expected in [(None, 'zh'), ('fr', 'zh'), ('en-GB', 'en'),
                ('en;q=0.1, zh-CN;q=0.9', 'zh'), ('zh;q=0,en;q=.5', 'en'),
                ('en;q=invalid,zh', 'zh'), ('en,zh', 'en')]:
            self.assertEqual(i18n.language(header), expected)

    def test_api_errors_and_security_rejection_switch_language(self):
        for headers, expected in [(EN, 'Invalid project ID.'), (ZH, '项目编号无效')]:
            response = self.client.get('/api/projects/not-an-id', headers=headers)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()['error'], expected)
            self.assertEqual(response.get_json()['error_translations'], {
                'zh-CN': '项目编号无效', 'en': 'Invalid project ID.'})
            self.assertIn('Accept-Language', response.headers['Vary'])
        response = self.client.post('/api/projects', data='bad JSON', content_type='application/json', headers=EN)
        self.assertEqual(response.get_json()['error'], 'A JSON request body is required.')
        response = self.client.post('/api/projects', json={}, headers={**EN, 'Origin': 'https://example.org'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['error'], 'Only the local Wencheng page can modify projects.')
        response = self.client.delete('/api/projects', headers=ZH)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.get_json()['error'], '此接口不支持该请求方法。')
        self.assertEqual(response.get_json()['error_translations']['en'], 'This endpoint does not support that request method.')
        response = self.client.post('/api/projects/import', data={'file': (BytesIO(b'not zip'), 'bad.docx')}, headers=EN)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error'], 'This file is not a valid DOCX document.')
        p = self.create()
        for content in (b'{broken json', b'\xff\xfe'):
            response = self.client.post(f"/api/projects/{p['id']}/tasks", headers=EN,
                data={'file': (BytesIO(content), 'results.json')})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()['error'], 'The result file is not valid UTF-8 JSON. Check its format.')

    def test_only_new_untitled_documents_use_the_requested_locale(self):
        en = self.ok(self.client.post('/api/projects', headers=EN, json={}))
        zh = self.ok(self.client.post('/api/projects', headers=ZH, json={}))
        self.assertEqual(en['title'], 'Untitled document')
        self.assertEqual(zh['title'], '未命名文档')
        self.assertEqual(self.get(zh['id'], EN)['title'], '未命名文档')
        self.assertEqual(self.get(en['id'], ZH)['title'], 'Untitled document')

    def test_rule_history_task_and_protection_metadata_switch_without_mutation(self):
        p = self.create(['需要强调的是，测得均值为 0.24，结果可能受温度影响 [1]。',
                         'It is important to note that the estimate may depend on temperature.'])
        pid = p['id']
        self.ok(self.client.patch(f'/api/projects/{pid}/settings', json={
            'rules': '自定规则：保留依据复述这个术语', 'style_sample': '需要 JSON 请求正文', 'language': 'auto'}))
        self.ok(self.client.post(f'/api/projects/{pid}/analyze', headers=EN))
        state = (store.directory(pid) / 'project.json').read_bytes()
        doc = store.document(pid)
        en, zh = self.get(pid, EN), self.get(pid, ZH)
        self.assertEqual(en['title'], p['title'])
        self.assertEqual(en['settings'], zh['settings'])
        self.assertEqual(en['settings']['style_sample'], '需要 JSON 请求正文')
        self.assertEqual([b['text'] for b in en['blocks']], [b['text'] for b in zh['blocks']])
        self.assertEqual(en['annotations'][0]['category'], 'Empty emphasis')
        self.assertEqual(zh['annotations'][0]['category'], '空泛强调')
        self.assertNotRegex(en['annotations'][0]['reason'], r'[\u4e00-\u9fff]')
        self.assertRegex(zh['annotations'][1]['instruction'], r'[\u4e00-\u9fff]')
        self.assertEqual(en['history'][-1]['label'], 'Flagged 2 writing issues')
        self.assertEqual(zh['history'][-1]['label'], '标记 2 处表达问题')
        self.assertEqual(en['blocks'][1]['protected'][0]['label'], 'Citation')
        self.assertEqual(zh['blocks'][1]['protected'][0]['label'], '引用标记')
        for headers in (EN, ZH):
            response = self.client.get(f'/api/projects/{pid}/tasks', headers=headers)
            payload = json.loads(response.data)
            self.assertEqual(payload['tasks'][0]['quote'], en['annotations'][0]['quote'])
            self.assertEqual(payload['tasks'][0]['context'], en['blocks'][1]['text'])
            self.assertEqual(payload['settings'], en['settings'])
            self.assertNotIn('_system_fields', payload['tasks'][0])
            if headers == EN:
                self.assertTrue(payload['instructions'].startswith('For each annotation,'))
                self.assertEqual(payload['tasks'][0]['category'], 'Empty emphasis')
            else:
                self.assertTrue(payload['instructions'].startswith('为每个标记'))
        self.assertEqual(state, (store.directory(pid) / 'project.json').read_bytes())
        self.assertEqual(doc, store.document(pid))

    def test_default_instruction_and_identical_user_instruction_are_distinguished(self):
        p = self.create(['alpha beta'])
        pid = p['id']
        default = '克制地改善表达，保留原意与正式文风。'
        for start, end, instruction in [(0, 5, None), (6, 10, default)]:
            value = dict(block_id='p1', start=start, end=end, quote=p['blocks'][1]['text'][start:end])
            if instruction is not None:
                value['instruction'] = instruction
            self.ok(self.client.post(f'/api/projects/{pid}/annotations', json=value, headers=EN))
        en = self.get(pid)
        self.assertEqual(en['annotations'][0]['instruction'], i18n.MESSAGES[default])
        self.assertEqual(en['annotations'][1]['instruction'], default)
        self.assertEqual(en['annotations'][1]['category'], 'User annotation')
        self.assertEqual(store.load(pid)['annotations'][0]['instruction'], default)

    def test_imported_reason_is_not_translated_even_if_equal_to_rule_reason(self):
        p = self.create()
        pid = p['id']
        scanned = self.ok(self.client.post(f'/api/projects/{pid}/analyze'))
        annotation = scanned['annotations'][0]
        reason = annotation['reason']
        replacement = '需要 JSON 请求正文'
        result = self.ok(self.client.post(f'/api/projects/{pid}/tasks', headers=EN, json={
            'project_id': pid, 'results': [{'id': annotation['id'], 'quote': annotation['quote'],
                                         'replacement': replacement, 'reason': reason}]}))
        self.assertEqual(result['annotations'][0]['reason'], reason)
        self.assertEqual(result['annotations'][0]['replacement'], replacement)
        self.assertEqual(result['annotations'][0]['category'], 'Empty emphasis')
        self.assertEqual(self.get(pid, ZH)['annotations'][0]['reason'], reason)
        self.assertEqual(self.get(pid, EN)['blocks'][1]['text'], p['blocks'][1]['text'])

    def test_protection_errors_and_summary_use_locale_without_offset_changes(self):
        p = self.ok(self.client.post('/api/projects/import', data={'file': (BytesIO(build_fixture()), 'fixture.docx')}))
        pid = p['id']
        en = self.get(pid)
        self.assertTrue(any(x['label'] == 'Equation' for x in en['protections']))
        for before, after in zip(p['blocks'], en['blocks']):
            self.assertEqual(before['text'], after['text'])
            self.assertEqual(before['runs'], after['runs'])
        for block in p['blocks']:
            region = next((x for x in block['protected'] if x['kind'] == 'formula' and x['end'] > x['start']), None)
            if region:
                response = self.client.post(f'/api/projects/{pid}/annotations', headers=EN, json={
                    'block_id': block['id'], 'start': region['start'], 'end': region['end'],
                    'quote': block['text'][region['start']:region['end']], 'instruction': '保留用户中文'})
                self.assertEqual(response.status_code, 400)
                self.assertIn('protected content (Equation)', response.get_json()['error'])
                break
        else:
            self.fail('Fixture has no equation')

    def test_provider_labels_and_config_values(self):
        value = {'provider': 'openai', 'model': '中文模型名', 'base_url': 'https://example.org/v1', 'api_key_env': 'MY_KEY'}
        en = self.ok(self.client.put('/api/providers', json=value, headers=EN))
        zh = self.ok(self.client.get('/api/providers', headers=ZH))
        self.assertEqual(en['config'], value)
        self.assertEqual(zh['config'], value)
        self.assertEqual(en['providers'][0]['label'], 'Local Codex')
        self.assertEqual(zh['providers'][0]['label'], '本机 Codex')

    def test_system_job_errors_can_switch_after_completion(self):
        p = self.create()
        message = 'codex 调用失败（退出码 2）：请在终端检查登录状态。'
        with patch.object(api.ai, 'generate', side_effect=ai.AIError(message)):
            jid = self.ok(self.client.post(f"/api/projects/{p['id']}/generate", json={'prompt': '中文要求'}, headers=ZH))['job_id']
            en = self.wait_job(jid)
        self.assertEqual(en['error'], 'The codex request failed (exit code 2): Check the login status in a terminal.')
        self.assertEqual(en['error_translations'], {'zh-CN': message, 'en': en['error']})
        self.assertEqual(en['status_label'], 'Task failed')
        self.assertEqual(en['progress_label'], 'Completed 0 items')
        zh = self.ok(self.client.get(f'/api/jobs/{jid}', headers=ZH))
        self.assertEqual(zh['error'], message)
        self.assertEqual(api.jobs[jid]['error'], message)
        self.assertNotIn('error_translations', api.jobs[jid])

    def test_external_job_error_details_are_preserved(self):
        p = self.create()
        external = '供应商说明：账户状态需要人工核实\n{"error": "配额不足"}'
        with patch.object(api.ai, 'generate', side_effect=ai.AIError('API 返回 HTTP 429：' + external)):
            jid = self.ok(self.client.post(f"/api/projects/{p['id']}/generate", json={'prompt': '要求'}, headers=EN))['job_id']
            en = self.wait_job(jid)
        self.assertEqual(en['error'], 'The API returned HTTP 429: ' + external)

    def test_ai_reason_locale_is_transient_for_sync_and_background_rewrite(self):
        p = self.create()
        pid = p['id']
        p = self.ok(self.client.post(f'/api/projects/{pid}/analyze'))
        aid = p['annotations'][0]['id']
        calls = []
        def rewrite(text, instruction, context, settings, config, **kwargs):
            calls.append(dict(settings))
            return {'replacement': text, 'reason': 'Model reason stays as returned.'}
        with patch.object(api.ai, 'rewrite', side_effect=rewrite):
            self.ok(self.client.post(f'/api/projects/{pid}/annotations/{aid}/suggest', headers=EN))
            jid = self.ok(self.client.post(f'/api/projects/{pid}/rewrite', headers=EN,
                                          json={'annotation_ids': [aid]}))['job_id']
            self.assertEqual(self.wait_job(jid)['status'], 'done')
        self.assertEqual([s['ui_language'] for s in calls], ['en', 'en'])
        self.assertNotIn('ui_language', store.load(pid)['settings'])
        with patch.object(ai, '_chunks', return_value=iter(['{"replacement":"中文原文","reason":"English reason"}'])) as chunks:
            result = ai.rewrite('中文原文', '保留数字', '', {'ui_language': 'en'}, {})
            prompt = chunks.call_args.args[0]
            self.assertIn('Write reason in English.', prompt)
            self.assertIn('Keep replacement in the original document language', prompt)
            self.assertEqual(result['replacement'], '中文原文')

    def test_all_static_backend_error_messages_have_english_translation(self):
        missing = []
        for path in (ROOT / 'backend').glob('*.py'):
            if path.name == 'i18n.py':
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
                    value = node.exc.args[0]
                    if isinstance(value, ast.Constant) and isinstance(value.value, str) and re.search(r'[\u4e00-\u9fff]', value.value):
                        if re.search(r'[\u4e00-\u9fff]', i18n.message(value.value, 'en')):
                            missing.append((path.name, node.lineno, value.value))
        self.assertEqual(missing, [])

    def test_dynamic_error_templates_and_rule_catalogue(self):
        messages = ['未找到 codex。请先安装并在终端完成登录，或选择 API。',
            'claude 请求超时，请重试或缩小处理范围。', 'codex 请求超时。',
            'codex 没有返回正文。请检查登录、模型设置及 CLI 版本。',
            '尚未设置环境变量 MY_APP_KEY。设置后重新启动文澄服务。',
            'PDF 校样需要包含 1 至 300 页。', 'PDF 第 42 页无法读取。',
            'PDF 第 38 页尺寸无效。', 'PDF 第 99 页过大，请使用常规论文纸张尺寸。',
            '选区包含受保护内容（footnote），请只选择相邻正文文字。',
            '操作失败：模型返回了空段落。']
        for source in messages:
            self.assertNotRegex(i18n.message(source, 'en'), r'[\u4e00-\u9fff]', source)
        for rule in rules.RULES:
            for field in ('category', 'instruction', 'reason'):
                self.assertNotRegex(i18n.message(rule[field], 'en'), r'[\u4e00-\u9fff]', (rule['id'], field))
        self.assertEqual(i18n.message('用户独立陈述，不是系统消息。', 'en'), '用户独立陈述，不是系统消息。')


if __name__ == '__main__':
    unittest.main()
