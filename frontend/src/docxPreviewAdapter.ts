import type { Options, WordDocument } from 'docx-preview';
import { translate } from './i18n.ts';

export const WORD_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';
export const OMML_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/math';
const MATHML_NS = 'http://www.w3.org/1998/Math/MathML';

interface PageField { token: string; kind: 'PAGE' | 'NUMPAGES'; cached: string; decimal: boolean }

function markPageField(instruction: string, text: Element[], fields: PageField[]) {
  const match = instruction.trim().match(/^(PAGE|NUMPAGES)(?=\s|$)(.*)$/i);
  if (!match || !text.length) return;
  const switches = match[2].replace(/\\\*\s+(?:MERGEFORMAT|Arabic)\b/gi, '').trim();
  const token = `\uE000wc-page-${crypto.randomUUID()}\uE001`;
  fields.push({ token, kind: match[1].toUpperCase() as PageField['kind'],
    cached: text.map(node => node.textContent || '').join(''), decimal: !switches });
  text[0].textContent = token;
  text.slice(1).forEach(node => { node.textContent = ''; });
}

function markComplexPageFields(document: Document, fields: PageField[]) {
  const stack: { instruction: string; result: boolean; text: Element[] }[] = [];
  for (const node of Array.from(document.getElementsByTagNameNS(WORD_NS, '*'))) {
    if (node.localName === 'fldChar') {
      const type = node.getAttributeNS(WORD_NS, 'fldCharType');
      if (type === 'begin') stack.push({ instruction: '', result: false, text: [] });
      else if (type === 'separate' && stack.length) stack.at(-1)!.result = true;
      else if (type === 'end' && stack.length) {
        const field = stack.pop()!;
        markPageField(field.instruction, field.text, fields);
      }
    } else if (stack.length && node.localName === 'instrText' && !stack.at(-1)!.result) {
      stack.at(-1)!.instruction += node.textContent || '';
    } else if (stack.length && node.localName === 't' && stack.at(-1)!.result) {
      stack.at(-1)!.text.push(node);
    }
  }
}

/** A deleted paragraph mark joins this paragraph to the next in Word's final view. */
function mergeDeletedParagraphMarks(document: Document) {
  const wordChild = (element: Element | undefined, name: string) => element && Array.from(element.children)
    .find(child => child.namespaceURI === WORD_NS && child.localName === name);
  let merged = 0;
  for (const paragraph of Array.from(document.getElementsByTagNameNS(WORD_NS, 'p'))) {
    const properties = wordChild(paragraph, 'pPr');
    if (!wordChild(wordChild(properties, 'rPr'), 'del')) continue;
    let next = paragraph.nextSibling;
    while (next && next.nodeType !== 1) next = next.nextSibling;
    if (!next || (next as Element).namespaceURI !== WORD_NS || (next as Element).localName !== 'p') continue;
    const following = next as Element;
    const followingProperties = wordChild(following, 'pPr');
    // The paragraph mark that survives supplies the resulting paragraph's format.
    // Moving forwards also handles chains, including newly inserted paragraphs.
    const before = followingProperties ? followingProperties.nextSibling : following.firstChild;
    for (const child of Array.from(paragraph.childNodes)) {
      if (child !== properties) following.insertBefore(child, before);
    }
    paragraph.parentNode!.removeChild(paragraph);
    merged++;
  }
  return merged;
}

/** Normalize a display-only XML clone for docx-preview 0.3.7's supported grammar. */
export function adaptPreviewXml(source: Document, pageFields: PageField[] = []) {
  const document = source.cloneNode(true) as Document;
  const mergedParagraphs = mergeDeletedParagraphMarks(document);
  const fields = Array.from(document.getElementsByTagNameNS(WORD_NS, 'fldSimple')).reverse();
  // Word stores the last computed result inside fldSimple. Display those runs;
  // Keep SEQ/REF results; mark PAGE/NUMPAGES for the display-only pass below.
  for (const field of fields) {
    markPageField(field.getAttributeNS(WORD_NS, 'instr') || '', Array.from(field.getElementsByTagNameNS(WORD_NS, 't')), pageFields);
    const parent = field.parentNode!;
    while (field.firstChild) parent.insertBefore(field.firstChild, field);
    parent.removeChild(field);
  }
  markComplexPageFields(document, pageFields);
  const scripts = Array.from(document.getElementsByTagNameNS(OMML_NS, 'sSubSup')).reverse();
  for (const combined of scripts) {
    const child = (name: string) => Array.from(combined.children).find(node => node.namespaceURI === OMML_NS && node.localName === name);
    const base = child('e'), sub = child('sub'), sup = child('sup');
    if (!base || !sub || !sup) throw new Error('公式的上下标结构不完整，无法可靠显示此预览。');
    // The library understands sSup and sSub, but drops sSubSup completely.
    // Preserve all three arguments, then combine the resulting MathML below.
    const upper = document.createElementNS(OMML_NS, 'm:sSup');
    const upperBase = document.createElementNS(OMML_NS, 'm:e');
    const lower = document.createElementNS(OMML_NS, 'm:sSub');
    lower.appendChild(base);
    lower.appendChild(sub);
    upperBase.appendChild(lower);
    upper.appendChild(upperBase);
    upper.appendChild(sup);
    combined.parentNode!.replaceChild(upper, combined);
  }
  return { document, fields: fields.length, scripts: scripts.length, mergedParagraphs };
}

interface PreviewNode {
  type?: string;
  children?: PreviewNode[];
  sectionProps?: SectionProps;
  props?: SectionProps;
  break?: string;
}
interface SectionProps {
  type?: string;
  pageSize?: { width?: string; height?: string; orientation?: string };
  headerRefs?: { type: string; id: string }[];
  footerRefs?: { type: string; id: string }[];
  pageNumber?: { start?: number | null; format?: string | null; chapStyle?: string | null };
}

export function usesContinuousDecimalPages(body: PreviewNode) {
  const sections = [...(body.children || []).filter(node => node.sectionProps).map(node => node.sectionProps!), body.props || {}];
  return sections.every((section, index) => {
    const numbering = section.pageNumber;
    return !numbering || (!numbering.chapStyle && (!numbering.format || numbering.format === 'decimal')
      && (numbering.start == null || (index === 0 && numbering.start === 1)));
  });
}

/** Make explicit section transitions before the renderer groups pages. */
export function adaptPreviewSections(body: PreviewNode) {
  const ends = (body.children || []).filter(node => node.type === 'paragraph' && node.sectionProps);
  const sections = [...ends.map(node => node.sectionProps!), body.props || {}];
  let headers: SectionProps['headerRefs'] = [], footers: SectionProps['footerRefs'] = [];
  for (const section of sections) {
    const inherit = (previous: NonNullable<SectionProps['headerRefs']>, current = previous) =>
      [...new Map([...previous, ...current].map(ref => [ref.type, { ...ref }])).values()];
    headers = inherit(headers, section.headerRefs);
    footers = inherit(footers, section.footerRefs);
    if (headers.length) section.headerRefs = headers;
    if (footers.length) section.footerRefs = footers;
  }
  let addedBreaks = 0;
  ends.forEach((paragraph, index) => {
    const current = sections[index], next = sections[index + 1];
    const type = next.type || 'nextPage'; // Word's default when w:type is absent.
    const changedSize = current.pageSize?.width !== next.pageSize?.width || current.pageSize?.height !== next.pageSize?.height;
    const startsNewPage = ['nextPage', 'oddPage', 'evenPage'].includes(type) || changedSize;
    if (!startsNewPage) return;
    const alreadyBreaks = paragraph.children?.some(run => run.children?.some(node => node.type === 'break' && ['page', 'lastRenderedPageBreak'].includes(node.break || '')));
    if (!alreadyBreaks) {
      (paragraph.children ||= []).push({ type: 'run', children: [{ type: 'break', break: 'page' }] });
      addedBreaks++;
    }
  });
  return addedBreaks;
}

export function combineRenderedScripts(container: HTMLElement) {
  for (const upper of Array.from(container.getElementsByTagNameNS(MATHML_NS, 'msup')).reverse()) {
    const [wrapper, sup] = Array.from(upper.children);
    if (upper.children.length !== 2 || wrapper?.localName !== 'mrow' || wrapper.children.length !== 1) continue;
    const lower = wrapper.firstElementChild!;
    if (lower.localName !== 'msub' || lower.children.length !== 2) continue;
    const [base, sub] = Array.from(lower.children);
    const combined = container.ownerDocument.createElementNS(MATHML_NS, 'msubsup');
    combined.appendChild(base);
    combined.appendChild(sub);
    combined.appendChild(sup);
    upper.parentNode!.replaceChild(combined, upper);
  }
}

/** Number the visible preview pages only; unsupported numbering stays labelled as cached. */
export function applyPreviewPageFields(pages: Element[], fields: PageField[], continuousDecimal: boolean, measuredPages = true) {
  const visit = (node: Node) => {
    if (node.nodeType !== 3) { Array.from(node.childNodes).forEach(visit); return; }
    const value = node.nodeValue || '';
    const present = fields.filter(field => value.includes(field.token));
    if (!present.length || !node.parentNode) return;
    let remainder = value;
    while (remainder) {
      const next = present.map(field => ({ field, offset: remainder.indexOf(field.token) }))
        .filter(item => item.offset >= 0).sort((a, b) => a.offset - b.offset)[0];
      if (!next) { node.parentNode.insertBefore(node.ownerDocument!.createTextNode(remainder), node); break; }
      if (next.offset) node.parentNode.insertBefore(node.ownerDocument!.createTextNode(remainder.slice(0, next.offset)), node);
      const marker = node.ownerDocument!.createElement('span');
      marker.setAttribute('data-wc-page-field', next.field.kind);
      marker.setAttribute('data-wc-page-cache', next.field.cached);
      marker.setAttribute('data-wc-page-supported', String(next.field.decimal && (next.field.kind === 'NUMPAGES' || continuousDecimal)));
      node.parentNode.insertBefore(marker, node);
      remainder = remainder.slice(next.offset + next.field.token.length);
    }
    node.parentNode.removeChild(node);
  };
  pages.forEach(visit);
  updatePreviewPageFields(pages, measuredPages);
}

/** Keep original cached values visible until connected DOM confirms page-sized blocks. */
export function updatePreviewPageFields(pages: Element[], measuredPages: boolean) {
  pages.forEach((page, index) => {
    for (const field of Array.from(page.getElementsByTagName('span'))) {
      const kind = field.getAttribute('data-wc-page-field');
      if (!kind) continue;
      const supported = measuredPages && field.getAttribute('data-wc-page-supported') === 'true';
      field.textContent = supported ? String(kind === 'PAGE' ? index + 1 : pages.length)
        : `${field.getAttribute('data-wc-page-cache') || ''}${translate('〔页码缓存〕')}`;
      field.setAttribute('title', translate(supported ? '按浏览器参考页计算，Word 页数请查看校样' : '原 DOCX 保存的页码结果，未按 HTML 内容重新分页'));
    }
  });
}

export function preparePreviewDocument(document: WordDocument) {
  const cachedPageBreaks = document.documentPart._xmlDocument?.getElementsByTagNameNS(WORD_NS, 'lastRenderedPageBreak').length || 0;
  const pageFields: PageField[] = [];
  let fields = 0, scripts = 0, mergedParagraphs = 0;
  for (const part of document.parts) {
    if (!part._documentParser || !part._xmlDocument) continue;
    const previousPageFields = pageFields.length;
    const adapted = adaptPreviewXml(part._xmlDocument, pageFields);
    fields += adapted.fields;
    scripts += adapted.scripts;
    mergedParagraphs += adapted.mergedParagraphs;
    if (adapted.fields || adapted.scripts || adapted.mergedParagraphs || pageFields.length > previousPageFields) part.parseXml(adapted.document.documentElement);
  }
  const continuousDecimal = usesContinuousDecimalPages(document.documentPart.body);
  const sectionBreaks = adaptPreviewSections(document.documentPart.body);
  return { fields, scripts, mergedParagraphs, sectionBreaks, pageFields, continuousDecimal, cachedPageBreaks };
}

/** Only transient preview parts are reparsed. No ZIP update or save is called. */
export async function renderAdaptedDocx(data: Blob, body: HTMLElement, styles?: HTMLElement, options?: Partial<Options>): Promise<WordDocument> {
  const { parseAsync, renderDocument } = await import('docx-preview');
  // keepOrigin is an internal 0.3.7 option: package version is intentionally pinned.
  const parseOptions = { ...options, keepOrigin: true };
  const document = await parseAsync(data, parseOptions);
  const prepared = preparePreviewDocument(document);
  await renderDocument(document, body, styles, options);
  combineRenderedScripts(body);
  const pages = Array.from(body.querySelectorAll('section'));
  pages[0]?.parentElement?.setAttribute('data-wc-cached-breaks', String(prepared.cachedPageBreaks));
  applyPreviewPageFields(pages, prepared.pageFields, prepared.continuousDecimal, false);
  return document;
}
