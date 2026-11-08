import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync, readdirSync } from 'node:fs';
import ts from 'typescript';
import { appMessages } from '../src/i18nApp.ts';
import { componentMessages } from '../src/i18nMessages.ts';
import { getLocale, initializeI18n, localeStorageKey, setLocale, translateForLocale } from '../src/i18n.ts';

test('English messages preserve interpolation values and arbitrary document text', () => {
  const dictionaries = { ...componentMessages, ...appMessages };
  const placeholders = (value: string) => [...value.matchAll(/\{(\w+)\}/g)].map(match => match[1]).sort();
  for (const [source, english] of Object.entries(dictionaries)) {
    assert.ok(english.trim(), `Empty translation: ${source}`);
    assert.deepEqual(placeholders(english), placeholders(source), `Interpolation mismatch: ${source}`);
  }
  assert.equal(translateForLocale('请求失败（{status}）', 'en', { status: 413 }), 'Request failed (413)');
  assert.equal(translateForLocale('请求失败（{status}）', 'zh-CN', { status: 413 }), '请求失败（413）');
  const authoredText = '用户自定义正文：实验结果提高 3.2 dB; Keep this exact wording.';
  assert.equal(translateForLocale(authoredText, 'en'), authoredText);
});

test('English interface counts use singular for one and plural for multiple items', () => {
  const cases = [
    ['{count} 段', '1 paragraph', '2 paragraphs'],
    ['{count} 字符', '1 character', '2 characters'],
    ['{count} 条标记', '1 annotation', '2 annotations'],
    ['{count} 条待处理标记', '1 open annotation', '2 open annotations'],
    ['已选 {count} 字符', '1 character selected', '2 characters selected'],
    ['已选文字 · {count} 字符', 'Selection · 1 character', 'Selection · 2 characters'],
    ['已完成 {count} 项，正在继续处理…', 'Completed 1 item. Processing the rest…', 'Completed 2 items. Processing the rest…'],
  ];
  for (const [source, singular, plural] of cases) {
    assert.equal(translateForLocale(source, 'en', { count: 1 }), singular);
    assert.equal(translateForLocale(source, 'en', { count: '1' }), singular, 'Formatted numeric strings also need singular agreement');
    assert.equal(translateForLocale(source, 'en', { count: 2 }), plural);
    assert.equal(translateForLocale(source, 'zh-CN', { count: 1 }), source.replace('{count}', '1'));
  }
});

test('language preference updates browser metadata and survives initialization without touching document state', () => {
  const stored = new Map<string, string>();
  const oldStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  const oldDocument = Object.getOwnPropertyDescriptor(globalThis, 'document');
  const documentStub = { title: '', documentElement: { lang: '' } };
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { setItem: (key: string, value: string) => stored.set(key, value) } });
  Object.defineProperty(globalThis, 'document', { configurable: true, value: documentStub });
  try {
    setLocale('en');
    initializeI18n();
    assert.equal(getLocale(), 'en');
    assert.equal(stored.get(localeStorageKey), 'en');
    assert.equal(documentStub.documentElement.lang, 'en');
    assert.equal(documentStub.title, 'Wencheng · Document review workspace');
    setLocale('zh-CN');
    assert.equal(documentStub.documentElement.lang, 'zh-CN');
    assert.equal(documentStub.title, '文澄 · 文档审阅工作台');
  } finally {
    if (oldStorage) Object.defineProperty(globalThis, 'localStorage', oldStorage); else delete (globalThis as any).localStorage;
    if (oldDocument) Object.defineProperty(globalThis, 'document', oldDocument); else delete (globalThis as any).document;
  }
});

test('rendered UI literals and translation calls do not leave untranslated Chinese labels', () => {
  const sourceDir = new URL('../src/', import.meta.url);
  const missing: string[] = [];
  const han = /\p{Script=Han}/u;
  for (const name of readdirSync(sourceDir).filter(name => /\.tsx?$/.test(name) && !name.startsWith('i18n'))) {
    const content = readFileSync(new URL(name, sourceDir), 'utf8');
    const source = ts.createSourceFile(name, content, ts.ScriptTarget.Latest, true, name.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const report = (node: ts.Node, value: string) => missing.push(`${name}:${source.getLineAndCharacterOfPosition(node.getStart()).line + 1}: ${value}`);
    function walk(node: ts.Node) {
      if (ts.isJsxText(node) && han.test(node.text) && node.text.trim() !== '中文') report(node, node.text.trim());
      if (ts.isCallExpression(node) && ['t', 'translate'].includes(node.expression.getText(source))) {
        const key = node.arguments[0];
        if (key && ts.isStringLiteral(key) && han.test(key.text) && translateForLocale(key.text, 'en') === key.text) report(node, key.text);
      }
      if (ts.isJsxAttribute(node) && node.initializer && ts.isStringLiteral(node.initializer) && han.test(node.initializer.text)) {
        const tag = node.parent.parent;
        if ((ts.isJsxOpeningElement(tag) || ts.isJsxSelfClosingElement(tag)) && /^[a-z]/.test(tag.tagName.getText(source))) report(node, node.initializer.text);
      }
      ts.forEachChild(node, walk);
    }
    walk(source);
  }
  assert.deepEqual(missing, [], `Untranslated UI strings:\n${missing.join('\n')}`);
});
