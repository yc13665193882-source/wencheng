import assert from 'node:assert/strict';
import test from 'node:test';
import { protectedPlaceholderDisplay } from '../src/protections.ts';

test('only exact generated placeholders with the matching protected kind get a display label', () => {
  const cases = [
    ['〔公式〕', 'formula', '[Equation]'],
    ['〔脚注12〕', 'footnote', '[Footnote 12]'],
    ['〔尾注-1〕', 'endnote', '[Endnote -1]'],
    ['〔脚注〕', 'footnote', '[Footnote]'],
    ['〔尾注〕', 'endnote', '[Endnote]'],
    ['〔图形〕', 'object', '[Drawing]'],
    ['〔符号〕', 'symbol', '[Symbol]'],
  ];
  for (const [text, kind, expected] of cases) {
    assert.equal(protectedPlaceholderDisplay(text, kind, 'en'), expected);
    assert.equal(protectedPlaceholderDisplay(text, kind, 'zh-CN'), text);
  }
  for (const [text, kind] of [
    ['正文〔公式〕', 'formula'], ['〔公式〕之后的文字', 'formula'], ['〔公式', 'formula'],
    ['〔公式〕', 'revision'], ['〔脚注1〕', 'endnote'], ['〔图形〕', 'hyperlink'],
    ['〔符号〕', 'unknown'], ['〔脚注-〕', 'footnote'], ['〔脚注abc〕', 'footnote'],
    ['ordinary protected text', 'formula'], ['\u00ad', 'symbol'],
  ]) assert.equal(protectedPlaceholderDisplay(text, kind, 'en'), null, `${kind}: ${text}`);
});

test('formula display preserves mathematical notation and user text after the generated prefix exactly', () => {
  const notation = 'α² + 中文变量 = 𝑥\n{notation}: keep [brackets]';
  const original = `〔公式：${notation}〕`;
  assert.equal(protectedPlaceholderDisplay(original, 'formula', 'en'), `[Equation: ${notation}]`);
  assert.equal(protectedPlaceholderDisplay(original, 'formula', 'zh-CN'), original);
  assert.equal(original, `〔公式：${notation}〕`);
});
