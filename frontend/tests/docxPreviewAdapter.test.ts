import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { DOMParser, XMLSerializer } from '@xmldom/xmldom';
import { parseAsync, renderDocument } from 'docx-preview';
import JSZip from 'jszip';
import { adaptPreviewXml, applyPreviewPageFields, combineRenderedScripts, preparePreviewDocument,
  updatePreviewPageFields, usesContinuousDecimalPages, WORD_NS, OMML_NS } from '../src/docxPreviewAdapter.ts';

// xmldom supplies real XML parsing but omits the browser convenience property
// used by docx-preview. No parser or DOCX objects are mocked in these tests.
const sample = new DOMParser().parseFromString('<x><y/></x>', 'application/xml');
for (const prototype of [Object.getPrototypeOf(sample), Object.getPrototypeOf(sample.documentElement)]) {
  Object.defineProperty(prototype, 'firstElementChild', { configurable: true,
    get() { return Array.from(this.childNodes).find((node: any) => node.nodeType === 1) || null; } });
}
Object.assign(globalThis, { DOMParser, XMLSerializer, Node: { ELEMENT_NODE: 1 } });
const serialize = (node: any) => new XMLSerializer().serializeToString(node);
const fixture = new URL('../../tests/fixtures/complex-academic.docx', import.meta.url);

function descendants(node: any, type?: string): any[] {
  return [node, ...(node.children || []).flatMap((child: any) => descendants(child))].filter(item => !type || item.type === type);
}
function text(node: any): string {
  return (typeof node.text === 'string' ? node.text : '') + (node.children || []).map(text).join('');
}
async function parsedFixture() {
  return parseAsync(await readFile(fixture), { keepOrigin: true } as any);
}

test('a real DOCX with chained deleted paragraph marks previews the final merged paragraphs without modifying its package', async () => {
  const zip = await JSZip.loadAsync(await readFile(fixture));
  const deletion = '<w:rPr><w:del w:id="21" w:author="文澄"/></w:rPr>';
  const insertion = '<w:rPr><w:ins w:id="22" w:author="文澄"/></w:rPr>';
  const xml = `<w:document xmlns:w="${WORD_NS}"><w:body>
    <w:p><w:pPr>${insertion}</w:pPr><w:r><w:t>前缀</w:t></w:r><w:ins w:id="23"><w:r><w:t>新第一段</w:t></w:r></w:ins></w:p>
    <w:p><w:pPr>${deletion}</w:pPr><w:ins w:id="24"><w:r><w:t>新第二段</w:t></w:r></w:ins><w:del w:id="25"><w:r><w:delText>旧首段</w:delText></w:r></w:del></w:p>
    <w:p><w:pPr>${deletion}</w:pPr><w:del w:id="26"><w:r><w:delText>旧中段</w:delText></w:r></w:del></w:p>
    <w:p><w:pPr><w:jc w:val="right"/></w:pPr><w:del w:id="27"><w:r><w:delText>旧末段</w:delText></w:r></w:del><w:r><w:t>后缀</w:t></w:r></w:p>
    <w:p><w:r><w:t>未修改下一段</w:t></w:r></w:p><w:sectPr/>
  </w:body></w:document>`;
  zip.file('word/document.xml', xml);
  const bytes = await zip.generateAsync({ type: 'nodebuffer' });
  const document = await parseAsync(bytes, { keepOrigin: true } as any);
  assert.equal(descendants(document.documentPart.body, 'paragraph').length, 5, 'Pinned parser reproduces ignored paragraph-mark deletions');
  const origin = serialize(document.documentPart._xmlDocument);
  const result = preparePreviewDocument(document);
  assert.equal(descendants(document.documentPart.body, 'paragraph').length, 3, 'Inserted paragraph break survives while deleted breaks are merged');
  assert.equal(result.mergedParagraphs, 2);
  const finalText = (node: any): string => node.type === 'deleted' ? '' : (typeof node.text === 'string' ? node.text : '') + (node.children || []).map(finalText).join('');
  assert.deepEqual(descendants(document.documentPart.body, 'paragraph').map(finalText), ['前缀新第一段', '新第二段后缀', '未修改下一段']);
  assert.equal(serialize(document.documentPart._xmlDocument), origin);
  assert.equal(await document._package.load('word/document.xml'), xml);
  const adapted = adaptPreviewXml(document.documentPart._xmlDocument);
  const paragraphs = Array.from(adapted.document.getElementsByTagNameNS(WORD_NS, 'p'));
  assert.equal(paragraphs[1].getElementsByTagNameNS(WORD_NS, 'jc')[0].getAttributeNS(WORD_NS, 'val'), 'right', 'The surviving paragraph mark retains its formatting');
});

test('display-only paragraph merges stay inside each table cell', () => {
  const source = new DOMParser().parseFromString(`<w:document xmlns:w="${WORD_NS}"><w:body><w:tbl><w:tr>
    <w:tc><w:p><w:pPr><w:rPr><w:del/></w:rPr></w:pPr><w:r><w:t>同格前</w:t></w:r></w:p><w:p><w:r><w:t>同格后</w:t></w:r></w:p></w:tc>
    <w:tc><w:p><w:pPr><w:rPr><w:del/></w:rPr></w:pPr><w:r><w:t>另一格</w:t></w:r></w:p></w:tc>
    <w:tc><w:p><w:r><w:t>不能跨格</w:t></w:r></w:p></w:tc>
  </w:tr></w:tbl></w:body></w:document>`, 'application/xml');
  const original = serialize(source);
  const adapted = adaptPreviewXml(source as any);
  assert.deepEqual(Array.from(adapted.document.getElementsByTagNameNS(WORD_NS, 'tc')).map(cell => cell.textContent), ['同格前同格后', '另一格', '不能跨格']);
  assert.equal(adapted.document.getElementsByTagNameNS(WORD_NS, 'p').length, 3);
  assert.equal(adapted.mergedParagraphs, 1);
  assert.equal(serialize(source), original);
});

test('real complex DOCX regains simultaneous scripts and simple-field cached caption numbers', async () => {
  const document = await parsedFixture();
  const beforeMath = descendants(document.documentPart.body, 'mmlMath').map(text);
  assert.ok(beforeMath.some(value => value.endsWith('+')), 'Pinned parser must reproduce the original missing-script bug');
  const result = preparePreviewDocument(document);
  assert.equal(result.scripts, 1);
  assert.equal(result.fields, 2);
  const afterMath = descendants(document.documentPart.body, 'mmlMath').map(text);
  assert.ok(afterMath.some(value => value.endsWith('+xi2')), JSON.stringify(afterMath));
  const paragraphs = descendants(document.documentPart.body, 'paragraph').map(text);
  assert.ok(paragraphs.some(value => /^图\s*1/.test(value)), 'Figure SEQ cached number must remain visible');
  assert.ok(paragraphs.some(value => /^表\s*1/.test(value)), 'Table SEQ cached number must remain visible');
});

test('real complex DOCX has four explicit page boundaries and portrait/landscape/portrait section sizes', async () => {
  const document = await parsedFixture();
  const result = preparePreviewDocument(document);
  assert.equal(result.sectionBreaks, 2);
  const body = document.documentPart.body;
  const breaks = descendants(body, 'break').filter(node => node.break === 'page');
  assert.equal(breaks.length, 4, 'Two manual page breaks plus two next-page section transitions yield five pages');
  const sections = [...body.children.filter((node: any) => node.sectionProps).map((node: any) => node.sectionProps), body.props];
  assert.deepEqual(sections.map(section => [section.pageSize.width, section.pageSize.height]),
    [['595.30pt', '841.90pt'], ['841.90pt', '595.30pt'], ['595.30pt', '841.90pt']]);
  assert.ok(sections.every(section => section.headerRefs?.length === 1 && section.footerRefs?.length === 1));
});

test('display adaptation leaves every origin XML and the source package bytes untouched', async () => {
  const bytes = await readFile(fixture);
  const document = await parsedFixture();
  const origins = document.parts.filter((part: any) => part._xmlDocument).map((part: any) => [part, serialize(part._xmlDocument)]);
  const originalPackage = await document._package.load('word/document.xml');
  preparePreviewDocument(document);
  for (const [part, original] of origins) assert.equal(serialize(part._xmlDocument), original, part.path);
  assert.equal(await document._package.load('word/document.xml'), originalPackage);
  assert.deepEqual(await readFile(fixture), bytes);
});

test('MathML combines the base, subscript and superscript without losing arguments', () => {
  const source = new DOMParser().parseFromString('<div xmlns:m="http://www.w3.org/1998/Math/MathML"><m:math><m:msup><m:mrow><m:msub><m:mrow><m:mi>x</m:mi></m:mrow><m:mn>i</m:mn></m:msub></m:mrow><m:mn>2</m:mn></m:msup></m:math></div>', 'application/xml');
  combineRenderedScripts(source.documentElement as any);
  const combined = source.getElementsByTagNameNS('http://www.w3.org/1998/Math/MathML', 'msubsup');
  assert.equal(combined.length, 1);
  assert.deepEqual(Array.from(combined[0].children).map(node => node.textContent), ['x', 'i', '2']);
});

test('shared footer PAGE and NUMPAGES use visible preview pages, with explicit fallback for restarts', async () => {
  const document = await parsedFixture();
  const result = preparePreviewDocument(document);
  assert.equal(result.continuousDecimal, true);
  assert.deepEqual(result.pageFields.map(field => field.kind).sort(), ['NUMPAGES', 'PAGE']);
  const page = result.pageFields.find(field => field.kind === 'PAGE')!;
  const total = result.pageFields.find(field => field.kind === 'NUMPAGES')!;
  const makePages = () => new DOMParser().parseFromString(`<div>${Array.from({ length: 5 }, () => `<section><footer>第 ${page.token} 页 共 ${total.token} 页</footer></section>`).join('')}</div>`, 'application/xml');
  const preview = makePages();
  applyPreviewPageFields(Array.from(preview.getElementsByTagName('section')) as any, result.pageFields, true);
  assert.deepEqual(Array.from(preview.getElementsByTagName('footer')).map(node => node.textContent),
    ['第 1 页 共 5 页', '第 2 页 共 5 页', '第 3 页 共 5 页', '第 4 页 共 5 页', '第 5 页 共 5 页']);
  assert.equal(usesContinuousDecimalPages({ children: [{ sectionProps: {} }], props: { pageNumber: { start: 9 } } }), false);
  assert.equal(usesContinuousDecimalPages({ props: { pageNumber: { format: 'upperRoman' } } }), false);
  const cached = makePages();
  applyPreviewPageFields(Array.from(cached.getElementsByTagName('section')) as any, result.pageFields, false);
  assert.ok(cached.getElementsByTagName('footer')[1].textContent.includes('1〔页码缓存〕'));
});

test('unsupported script structure raises a preview error instead of dropping text', () => {
  const document = new DOMParser().parseFromString(`<w:document xmlns:w="${WORD_NS}" xmlns:m="${OMML_NS}"><m:oMath><m:sSubSup><m:e><m:r><m:t>x</m:t></m:r></m:e></m:sSubSup></m:oMath></w:document>`, 'application/xml');
  assert.throws(() => adaptPreviewXml(document as any), /上下标结构不完整/);
});

test('overflowing HTML blocks never replace the source NUMPAGES cache with a false block count', async () => {
  const document = await parsedFixture();
  const { pageFields } = preparePreviewDocument(document);
  const total = pageFields.find(field => field.kind === 'NUMPAGES')!;
  const page = pageFields.find(field => field.kind === 'PAGE')!;
  const preview = new DOMParser().parseFromString(`<div>${Array.from({ length: 4 }, () => `<section><footer>${page.token} / ${total.token}</footer></section>`).join('')}</div>`, 'application/xml');
  const pages = Array.from(preview.getElementsByTagName('section')) as any;
  applyPreviewPageFields(pages, pageFields, true, false);
  assert.equal(pages[3].textContent, '1〔页码缓存〕 / 5〔页码缓存〕');
  updatePreviewPageFields(pages, true);
  assert.equal(pages[3].textContent, '4 / 4');
  // A late-loaded image/font may overflow an initially fitting page: restore source caches.
  updatePreviewPageFields(pages, false);
  assert.equal(pages[3].textContent, '1〔页码缓存〕 / 5〔页码缓存〕');
});

test('the real DOCX revision paragraph renders inserted text and omits deleted text in final view', async () => {
  const parsed = await parsedFixture();
  const paragraph = descendants(parsed.documentPart.body, 'paragraph').find(node =>
    descendants(node, 'inserted').length && descendants(node, 'deleted').length);
  assert.ok(paragraph, 'The fixture must contain an original tracked insertion and deletion');
  const inserted = descendants(paragraph, 'inserted').map(text).join('');
  const deleted = descendants(paragraph, 'deleted').map(text).join('');
  assert.ok(inserted && deleted && inserted !== deleted);

  // Use the library's actual DOM renderer. Only browser CSS plumbing is shimmed;
  // insertion/deletion handling, child traversal and output text are not mocked.
  const html = new DOMParser().parseFromString('<html><body/></html>', 'application/xml');
  const createElement = html.createElement.bind(html);
  html.createElement = ((name: string) => {
    const element = createElement(name) as any;
    element.style = {};
    element.classList = { add() {} };
    return element;
  }) as any;
  const previousWindow = globalThis.window;
  const previousDocument = globalThis.document;
  Object.assign(globalThis, { window: { document: html }, document: html });
  try {
    const render = async (renderChanges: boolean) => {
      const body = html.createElement('div'), styles = html.createElement('div');
      await renderDocument({ documentPart: { body: { type: 'document', children: [paragraph], props: {} } } } as any,
        body as any, styles as any, { renderChanges, renderComments: false });
      return body;
    };
    const markup = await render(true);
    assert.ok(markup.textContent?.includes(deleted), 'Control: markup mode reproduces deleted text in HTML');
    assert.ok(markup.getElementsByTagName('del').length > 0);
    const finalView = await render(false);
    assert.ok(finalView.textContent?.includes(inserted), 'Insertion must remain in the final text');
    assert.ok(!finalView.textContent?.includes(deleted), 'Deleted text must not appear or occupy layout space');
    assert.equal(finalView.getElementsByTagName('del').length, 0);
    assert.equal(finalView.getElementsByTagName('ins').length, 0, 'Inserted text is rendered without revision decoration');
  } finally {
    Object.assign(globalThis, { window: previousWindow, document: previousDocument });
  }
});
