import type { Block, Selection } from './types';

export type SelectionPoint = { block_id: string; offset: number };
export type SelectionSlice = { block: Block; start: number; end: number };

export function selectionSlices(selection: Selection, blocks: Block[]): SelectionSlice[] {
  const first = blocks.findIndex(block => block.id === selection.block_id);
  const last = blocks.findIndex(block => block.id === (selection.end_block_id || selection.block_id));
  if (first < 0 || last < first || !Number.isInteger(selection.start) || !Number.isInteger(selection.end) || selection.start < 0 || selection.end < 0 ||
    selection.start > Array.from(blocks[first].text).length || selection.end > Array.from(blocks[last].text).length ||
    (first === last && selection.start > selection.end)) return [];
  return blocks.slice(first, last + 1).map((block, index) => ({ block,
    start: index === 0 ? selection.start : 0,
    end: index === last - first ? selection.end : Array.from(block.text).length,
  }));
}

export function selectionFromEndpoints(blocks: Block[], blockId: string, start: number, endBlockId: string, end: number): Selection | null {
  const selected: Selection = { block_id: blockId, start, end, quote: '', ...(endBlockId !== blockId ? { end_block_id: endBlockId } : {}) };
  const slices = selectionSlices(selected, blocks);
  if (!slices.length) return null;
  selected.quote = slices.map(({ block, start: from, end: to }) => Array.from(block.text).slice(from, to).join('')).join('\n');
  return selected;
}

export function readParagraphSelection(root: HTMLElement, blocks: Block[], current = root.ownerDocument.getSelection()): Selection | 'cross-block' | null {
  if (!current || current.isCollapsed || !current.rangeCount) return null;
  const range = current.getRangeAt(0);
  const parentElement = (node: Node) => node.nodeType === 1 ? node as Element : node.parentElement;
  const element = parentElement(range.startContainer)?.closest<HTMLElement>('[data-block-text]');
  if (!element || !root.contains(element)) return null;
  const endElement = parentElement(range.endContainer)?.closest<HTMLElement>('[data-block-text]');
  if (!endElement || !root.contains(endElement) || !endElement.dataset?.blockText) return 'cross-block';
  const block = blocks.find(item => item.id === element.dataset.blockText);
  if (!block) return null;
  const before = range.cloneRange();
  before.selectNodeContents(element);
  before.setEnd(range.startContainer, range.startOffset);
  const start = Array.from(before.toString()).length;
  let end: number;
  if (element === endElement) end = start + Array.from(range.toString()).length;
  else {
    const throughEnd = range.cloneRange();
    throughEnd.selectNodeContents(endElement);
    throughEnd.setEnd(range.endContainer, range.endOffset);
    end = Array.from(throughEnd.toString()).length;
  }
  const selected = selectionFromEndpoints(blocks, block.id, start, endElement.dataset.blockText!, end);
  if (!selected || (element === endElement && selected.quote !== range.toString())) return null;
  return selected;
}

export function observeParagraphSelection(root: HTMLElement, blocks: () => Block[], onSelect: (selection: Selection) => void, onInvalid: () => void) {
  let last = '';
  const collect = (event: Event) => {
    const result = readParagraphSelection(root, blocks());
    if (!result) { last = ''; return; }
    // During a drag, the native caret may briefly pass through a paragraph's
    // gutter or container boundary. Keep the last useful range until release.
    if (result === 'cross-block' && event.type === 'selectionchange') { last = ''; return; }
    const key = typeof result === 'string' ? result : `${result.block_id}:${result.start}:${result.end_block_id || result.block_id}:${result.end}:${result.quote}`;
    if (key === last) return;
    last = key;
    if (result === 'cross-block') onInvalid();
    else onSelect(result);
  };
  root.addEventListener('mouseup', collect);
  root.addEventListener('keyup', collect);
  root.ownerDocument.addEventListener('selectionchange', collect);
  return () => {
    root.removeEventListener('mouseup', collect);
    root.removeEventListener('keyup', collect);
    root.ownerDocument.removeEventListener('selectionchange', collect);
  };
}

/** The document model counts Unicode code points; DOM Range counts UTF-16 units. */
export function paragraphRange(element: HTMLElement, start: number, end: number) {
  const document = element.ownerDocument;
  const walker = document.createTreeWalker(element, 4 /* SHOW_TEXT */);
  const nodes: Text[] = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) nodes.push(node as Text);
  const point = (offset: number) => {
    let remaining = offset;
    for (const node of nodes) {
      const characters = Array.from(node.data);
      if (remaining <= characters.length) return { node, offset: characters.slice(0, remaining).join('').length };
      remaining -= characters.length;
    }
    const node = nodes.at(-1);
    return node ? { node, offset: node.length } : null;
  };
  const first = point(start), last = point(end);
  const range = document.createRange();
  if (!first || !last) { range.setStart(element, 0); range.setEnd(element, 0); return range; }
  range.setStart(first.node, first.offset);
  range.setEnd(last.node, last.offset);
  return range;
}

export function offsetAtPoint(element: HTMLElement, x: number, y: number): number | null {
  const document = element.ownerDocument as Document & {
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
    caretRangeFromPoint?: (x: number, y: number) => Range | null;
  };
  const position = document.caretPositionFromPoint?.(x, y);
  const caret = position ? null : document.caretRangeFromPoint?.(x, y);
  const node = position?.offsetNode || caret?.startContainer;
  const offset = position?.offset ?? caret?.startOffset;
  if (!node || offset === undefined || !element.contains(node)) return null;
  const before = document.createRange();
  before.selectNodeContents(element);
  before.setEnd(node, offset);
  return Array.from(before.toString()).length;
}

export function moveSelectionEdge(selection: Selection, text: string, edge: 'start' | 'end', offset: number): Selection {
  const chars = Array.from(text);
  const start = edge === 'start' ? Math.max(0, Math.min(offset, selection.end - 1)) : selection.start;
  const end = edge === 'end' ? Math.min(chars.length, Math.max(offset, selection.start + 1)) : selection.end;
  return { ...selection, start, end, quote: chars.slice(start, end).join('') };
}

/** A paragraph break occupies one model character while moving across the document. */
function documentPosition(blocks: Block[], point: SelectionPoint): number | null {
  let position = 0;
  for (const block of blocks) {
    const length = Array.from(block.text).length;
    if (block.id === point.block_id) return position + Math.max(0, Math.min(point.offset, length));
    position += length + 1;
  }
  return null;
}

function pointAtDocumentPosition(blocks: Block[], position: number): SelectionPoint {
  let remaining = Math.max(0, position);
  for (const block of blocks) {
    const length = Array.from(block.text).length;
    if (remaining <= length) return { block_id: block.id, offset: remaining };
    remaining -= length + 1;
  }
  const last = blocks[blocks.length - 1];
  return { block_id: last.id, offset: Array.from(last.text).length };
}

export function moveDocumentSelectionEdge(selection: Selection, blocks: Block[], edge: 'start' | 'end', point: SelectionPoint): Selection {
  const start = documentPosition(blocks, { block_id: selection.block_id, offset: selection.start });
  const end = documentPosition(blocks, { block_id: selection.end_block_id || selection.block_id, offset: selection.end });
  const desired = documentPosition(blocks, point);
  if (start === null || end === null || desired === null) return selection;
  const from = pointAtDocumentPosition(blocks, edge === 'start' ? Math.min(desired, end - 1) : start);
  const to = pointAtDocumentPosition(blocks, edge === 'end' ? Math.max(desired, start + 1) : end);
  return selectionFromEndpoints(blocks, from.block_id, from.offset, to.block_id, to.offset) || selection;
}

export function stepDocumentSelectionEdge(selection: Selection, blocks: Block[], edge: 'start' | 'end', delta: number): Selection {
  const position = documentPosition(blocks, { block_id: edge === 'start' ? selection.block_id : selection.end_block_id || selection.block_id, offset: selection[edge] });
  if (position === null) return selection;
  return moveDocumentSelectionEdge(selection, blocks, edge, pointAtDocumentPosition(blocks, position + delta));
}

export function selectionPointAtCoordinates(root: HTMLElement, x: number, y: number): SelectionPoint | null {
  // Restrict hit testing to document text so paragraph numbers and mark badges never enter a quote.
  const elements = Array.from(root.querySelectorAll<HTMLElement>('[data-block-text]'));
  const element = elements.find(item => { const rect = item.getBoundingClientRect(); return y >= rect.top && y <= rect.bottom; });
  if (!element) return null;
  const rect = element.getBoundingClientRect();
  const offset = offsetAtPoint(element, Math.max(rect.left + 1, Math.min(x, rect.right - 1)), y);
  return offset === null ? null : { block_id: element.dataset.blockText!, offset };
}

export function pressedSelection(block: Block, offset: number): Selection {
  const chars = Array.from(block.text);
  let start = Math.max(0, Math.min(offset, chars.length - 1));
  let end = start + 1;
  if (/^[a-z0-9_]$/i.test(chars[start])) {
    while (start > 0 && /^[a-z0-9_]$/i.test(chars[start - 1])) start--;
    while (end < chars.length && /^[a-z0-9_]$/i.test(chars[end])) end++;
  }
  return { block_id: block.id, start, end, quote: chars.slice(start, end).join('') };
}

export function showNativeSelection(element: HTMLElement, selection: Selection) {
  const range = paragraphRange(element, selection.start, selection.end);
  if (!range) return;
  const current = element.ownerDocument.getSelection();
  current?.removeAllRanges();
  current?.addRange(range);
}

export function showDocumentSelection(root: HTMLElement, selection: Selection) {
  const first = root.querySelector<HTMLElement>(`[data-block-text="${selection.block_id}"]`);
  const last = root.querySelector<HTMLElement>(`[data-block-text="${selection.end_block_id || selection.block_id}"]`);
  if (!first || !last) return;
  const start = paragraphRange(first, selection.start, selection.start);
  const end = paragraphRange(last, selection.end, selection.end);
  if (!start || !end) return;
  const range = root.ownerDocument.createRange();
  range.setStart(start.startContainer, start.startOffset);
  range.setEnd(end.endContainer, end.endOffset);
  const native = root.ownerDocument.getSelection();
  native?.removeAllRanges();
  native?.addRange(range);
}

/** Touch uses the browser's own long press; a mouse press gains the same entry point. */
export function observeMouseLongPress(root: HTMLElement, blocks: () => Block[], onSelect: (selection: Selection) => void) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let origin: { x: number; y: number; pointerId: number } | null = null;
  const cancel = () => { clearTimeout(timer); timer = undefined; origin = null; };
  const start = (event: PointerEvent) => {
    cancel();
    if (event.pointerType !== 'mouse' || event.button !== 0 || !event.isPrimary) return;
    const element = (event.target as Element).closest<HTMLElement>('[data-block-text]');
    const block = blocks().find(item => item.id === element?.dataset.blockText);
    if (!element || !block?.text) return;
    origin = { x: event.clientX, y: event.clientY, pointerId: event.pointerId };
    timer = setTimeout(() => {
      if (!origin) return;
      const offset = offsetAtPoint(element, origin.x, origin.y);
      if (offset === null) return;
      const selection = pressedSelection(block, offset);
      showNativeSelection(element, selection);
      onSelect(selection);
    }, 450);
  };
  const move = (event: PointerEvent) => {
    if (origin?.pointerId === event.pointerId && Math.hypot(event.clientX - origin.x, event.clientY - origin.y) > 8) cancel();
  };
  root.addEventListener('pointerdown', start);
  root.ownerDocument.addEventListener('pointermove', move);
  root.ownerDocument.addEventListener('pointerup', cancel);
  root.ownerDocument.addEventListener('pointercancel', cancel);
  root.ownerDocument.addEventListener('scroll', cancel, true);
  return () => {
    cancel();
    root.removeEventListener('pointerdown', start);
    root.ownerDocument.removeEventListener('pointermove', move);
    root.ownerDocument.removeEventListener('pointerup', cancel);
    root.ownerDocument.removeEventListener('pointercancel', cancel);
    root.ownerDocument.removeEventListener('scroll', cancel, true);
  };
}
