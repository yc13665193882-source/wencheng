import assert from 'node:assert/strict';
import test from 'node:test';
import { api, post } from '../src/api.ts';
import { setLocale, translate } from '../src/i18n.ts';

test('API sends interface locale separately from authored request data', async () => {
  const originalFetch = globalThis.fetch;
  const requests: RequestInit[] = [];
  globalThis.fetch = async (_input, init) => {
    requests.push(init || {});
    return new Response(JSON.stringify({ ok: true }), { headers: { 'Content-Type': 'application/json' } });
  };
  try {
    const body = { instruction: '保留这条中文要求', language: 'zh' };
    setLocale('en');
    await post('/projects/example/annotations', body);
    assert.equal(new Headers(requests[0].headers).get('Accept-Language'), 'en');
    assert.deepEqual(JSON.parse(requests[0].body as string), body);
    setLocale('zh-CN');
    await api('/projects/example');
    assert.equal(new Headers(requests[1].headers).get('Accept-Language'), 'zh-CN');
  } finally { globalThis.fetch = originalFetch; setLocale('zh-CN'); }
});

test('network and non-JSON HTTP errors use the selected interface language', async () => {
  const originalFetch = globalThis.fetch;
  try {
    setLocale('en');
    globalThis.fetch = async () => new Response('Unavailable', { status: 503 });
    await assert.rejects(api('/providers'), /Request failed \(503\)/);
    globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
    await assert.rejects(api('/providers'), /Cannot connect to the local service/);
    setLocale('zh-CN');
    await assert.rejects(api('/providers'), /连接本地服务失败/);
  } finally { globalThis.fetch = originalFetch; setLocale('zh-CN'); }
});

test('a language change during save refreshes localized metadata without repeating the write', async () => {
  const originalFetch = globalThis.fetch;
  const requests: { path: string; method: string; locale: string | null }[] = [];
  globalThis.fetch = async (input, init) => {
    const language = new Headers(init?.headers).get('Accept-Language');
    requests.push({ path: String(input), method: init?.method || 'GET', locale: language });
    if (requests.length === 1) setLocale('en');
    return new Response(JSON.stringify({ id: 'test-project', blocks: [], annotations: [], history: [{ label: language === 'en' ? 'Annotation added' : '添加修改标记' }] }));
  };
  try {
    setLocale('zh-CN');
    const result = await post<any>('/projects/test-project/annotations', { instruction: 'Keep wording' });
    assert.deepEqual(requests.map(request => request.method), ['POST', 'GET']);
    assert.equal(requests[1].path, '/api/projects/test-project');
    assert.equal(requests[1].locale, 'en');
    assert.equal(result.history[0].label, 'Annotation added');
  } finally { globalThis.fetch = originalFetch; setLocale('zh-CN'); }
});

test('server errors remain translatable after the request has completed', async () => {
  const originalFetch = globalThis.fetch;
  const pair = { 'zh-CN': '测试服务器错误：42', en: 'Test server error: 42' };
  globalThis.fetch = async () => new Response(JSON.stringify({ error: pair.en, error_translations: pair }), { status: 400 });
  try {
    setLocale('en');
    let shown = '';
    try { await api('/missing'); } catch (error) { shown = (error as Error).message; }
    assert.equal(shown, pair.en);
    setLocale('zh-CN');
    assert.equal(translate(shown), pair['zh-CN']);
  } finally { globalThis.fetch = originalFetch; setLocale('zh-CN'); }
});
