import assert from 'node:assert/strict';
import test from 'node:test';
import { moveDocumentSelectionEdge, moveSelectionEdge, observeMouseLongPress, observeParagraphSelection, paragraphRange, pressedSelection, readParagraphSelection, selectionFromEndpoints, selectionSlices, stepDocumentSelectionEdge } from '../src/textSelection.ts';

test('a native drag across paragraphs captures one exact quote without paragraph numbers or annotation controls', () => {
  const blocks = ['首😀段的末尾', '中间整段', '末段的开头后缀'].map((text, index) => ({ id: `p${index}`, text, kind: 'paragraph', editable: true, protected: [] }));
  const elements: any[] = blocks.map(block => ({ dataset: { blockText: block.id } }));
  elements.forEach(element => { element.closest = () => element; });
  const nodes = elements.map((element, index) => ({ nodeType: 3, parentElement: element, data: blocks[index].text }));
  const range: any = {
    startContainer: nodes[0], startOffset: 4, endContainer: nodes[2], endOffset: 5,
    toString: () => '的末尾02中间整段查看标记03末段的开头',
    cloneRange: () => {
      let node: any, offset = 0;
      return { selectNodeContents() {}, setEnd(n: any, o: number) { node = n; offset = o; }, toString: () => node.data.slice(0, offset) };
    },
  };
  const document = Object.assign(new EventTarget(), { getSelection: () => ({ isCollapsed: false, rangeCount: 1, getRangeAt: () => range }) });
  const root = Object.assign(new EventTarget(), { ownerDocument: document, contains: (element: any) => elements.includes(element) });
  const selected: any[] = [];
  let invalid = 0;
  const dispose = observeParagraphSelection(root as any, () => blocks, value => selected.push(value), () => invalid++);
  try {
    document.dispatchEvent(new Event('selectionchange'));
    assert.deepEqual(selected.at(-1), { block_id: 'p0', end_block_id: 'p2', start: 3, end: 5, quote: '的末尾\n中间整段\n末段的开头' });
    assert.equal(invalid, 0, 'continuous paragraphs must be selectable');
  } finally { dispose(); }
});

function fixture() {
  const text = '前😀正文里的句子，后文。';
  const block = { id: 'p1', text, kind: 'paragraph', editable: true, protected: [] };
  const element: any = { dataset: { blockText: 'p1' }, closest: () => element };
  const textNode: any = { nodeType: 3, parentElement: element };
  let start = 3;
  let end = 7;
  let crossBlock = false;
  const selection: any = { isCollapsed: false, rangeCount: 1, getRangeAt: () => ({
    startContainer: textNode, startOffset: start,
    endContainer: crossBlock ? { nodeType: 3, parentElement: { closest: () => ({}) } } : textNode,
    toString: () => Array.from(text).slice(start, end).join(''),
    cloneRange: () => ({ selectNodeContents() {}, setEnd() {}, toString: () => Array.from(text).slice(0, start).join('') }),
  }) };
  const document = Object.assign(new EventTarget(), { getSelection: () => selection });
  const root = Object.assign(new EventTarget(), { ownerDocument: document, contains: (node: any) => node === element });
  const selected: any[] = [];
  let invalid = 0;
  const dispose = observeParagraphSelection(root as any, () => [block], value => selected.push(value), () => invalid++);
  return { root, document, selection, block, selected, dispose, invalid: () => invalid,
    change: (a: number, b: number) => { start = a; end = b; }, cross: () => { crossBlock = true; } };
}

test('touch selection and native handle adjustments update the saved exact range without a mouse event', () => {
  const f = fixture();
  try {
    f.document.dispatchEvent(new Event('selectionchange'));
    assert.deepEqual(f.selected.at(-1), { block_id: 'p1', start: 3, end: 7, quote: '文里的句' });
    f.change(1, 8);
    f.document.dispatchEvent(new Event('selectionchange'));
    assert.deepEqual(f.selected.at(-1), { block_id: 'p1', start: 1, end: 8, quote: '😀正文里的句子' });
  } finally { f.dispose(); }
});

test('mouse selections retain code-point offsets and reject endpoints outside the document', () => {
  const f = fixture();
  try {
    f.root.dispatchEvent(new Event('mouseup'));
    assert.deepEqual(f.selected[0], { block_id: 'p1', start: 3, end: 7, quote: '文里的句' });
    f.cross();
    f.document.dispatchEvent(new Event('selectionchange'));
    assert.equal(f.invalid(), 0, 'a transient container boundary during dragging must not clear the useful range');
    f.root.dispatchEvent(new Event('mouseup'));
    assert.equal(f.invalid(), 1);
    assert.equal(f.selected.length, 1);
  } finally { f.dispose(); }
});

test('paragraph slices drive complete annotation highlights while invalid stale endpoints are rejected', () => {
  const blocks = ['前😀末', '', '后文'].map((text, index) => ({ id: `p${index}`, text, kind: 'paragraph', editable: true, protected: [] }));
  const selection = selectionFromEndpoints(blocks, 'p0', 1, 'p2', 1)!;
  assert.deepEqual(selection, { block_id: 'p0', end_block_id: 'p2', start: 1, end: 1, quote: '😀末\n\n后' });
  assert.deepEqual(selectionSlices(selection, blocks), [
    { block: blocks[0], start: 1, end: 3 }, { block: blocks[1], start: 0, end: 0 }, { block: blocks[2], start: 0, end: 1 },
  ]);
  assert.equal(selectionFromEndpoints(blocks, 'p0', 9, 'p2', 1), null);
  assert.equal(selectionFromEndpoints(blocks, 'p0', 1, 'missing', 1), null);
  assert.equal(selectionFromEndpoints(blocks, 'p2', 0, 'p0', 1), null);
  assert.equal(selectionFromEndpoints(blocks, 'p0', 1, 'p2', 9), null);
  assert.equal(selectionFromEndpoints(blocks, 'p0', 1.5, 'p2', 1), null);
});

test('dragging either endpoint expands across paragraphs and can shrink back to one paragraph', () => {
  const blocks = ['前😀末', '中间', '后文'].map((text, index) => ({ id: `p${index}`, text, kind: 'paragraph', editable: true, protected: [] }));
  const selected = selectionFromEndpoints(blocks, 'p1', 0, 'p1', 2)!;
  const expandedStart = moveDocumentSelectionEdge(selected, blocks, 'start', { block_id: 'p0', offset: 1 });
  assert.deepEqual(expandedStart, { block_id: 'p0', end_block_id: 'p1', start: 1, end: 2, quote: '😀末\n中间' });
  const expandedEnd = moveDocumentSelectionEdge(expandedStart, blocks, 'end', { block_id: 'p2', offset: 1 });
  assert.equal(expandedEnd.quote, '😀末\n中间\n后');
  const shrunk = moveDocumentSelectionEdge(expandedEnd, blocks, 'end', { block_id: 'p0', offset: 3 });
  assert.deepEqual(shrunk, { block_id: 'p0', start: 1, end: 3, quote: '😀末' });
  assert.deepEqual(moveDocumentSelectionEdge(selected, blocks, 'start', { block_id: 'p2', offset: 2 }),
    { block_id: 'p1', start: 1, end: 2, quote: '间' }, 'endpoints cannot cross');
});

test('arrow key micro-adjustment can cross paragraph breaks and empty paragraphs without splitting emoji', () => {
  const blocks = ['前😀', '', '后文'].map((text, index) => ({ id: `p${index}`, text, kind: 'paragraph', editable: true, protected: [] }));
  let selected = selectionFromEndpoints(blocks, 'p2', 0, 'p2', 1)!;
  selected = stepDocumentSelectionEdge(selected, blocks, 'start', -1);
  assert.deepEqual(selected, { block_id: 'p1', end_block_id: 'p2', start: 0, end: 1, quote: '\n后' });
  selected = stepDocumentSelectionEdge(selected, blocks, 'start', -1);
  assert.equal(selected.quote, '\n\n后');
  selected = stepDocumentSelectionEdge(selected, blocks, 'start', -1);
  assert.equal(selected.quote, '😀\n\n后');
  let end = selectionFromEndpoints(blocks, 'p0', 0, 'p0', 2)!;
  end = stepDocumentSelectionEdge(end, blocks, 'end', 1);
  assert.deepEqual(end, { block_id: 'p0', end_block_id: 'p1', start: 0, end: 0, quote: '前😀\n' });
  end = stepDocumentSelectionEdge(end, blocks, 'end', -1);
  assert.deepEqual(end, { block_id: 'p0', start: 0, end: 2, quote: '前😀' });
});

test('selection listeners are disposed and duplicate browser events do not reopen the sidebar', () => {
  const f = fixture();
  f.root.dispatchEvent(new Event('mouseup'));
  f.document.dispatchEvent(new Event('selectionchange'));
  assert.equal(f.selected.length, 1);
  f.dispose();
  f.change(1, 8);
  f.root.dispatchEvent(new Event('mouseup'));
  f.document.dispatchEvent(new Event('selectionchange'));
  assert.equal(f.selected.length, 1);
  f.selection.isCollapsed = true;
  assert.equal(readParagraphSelection(f.root as any, [f.block]), null);
});

test('selection endpoints map code points across text nodes and marked text without splitting emoji', () => {
  const nodes = ['前😀', '正文', '后文'].map(data => ({ data, length: data.length }));
  const range: any = { setStart(node: any, offset: number) { this.start = { node, offset }; }, setEnd(node: any, offset: number) { this.end = { node, offset }; } };
  const element: any = { ownerDocument: { createTreeWalker: () => {
    let index = 0;
    return { nextNode: () => nodes[index++] || null };
  }, createRange: () => range } };
  assert.equal(paragraphRange(element, 1, 4), range);
  assert.deepEqual(range.start, { node: nodes[0], offset: 1 });
  assert.deepEqual(range.end, { node: nodes[1], offset: 2 });
  paragraphRange(element, 2, 5);
  assert.deepEqual(range.start, { node: nodes[0], offset: 3 }, 'after the emoji is three UTF-16 units, but two model characters');
  assert.deepEqual(range.end, { node: nodes[2], offset: 1 });
});

test('dragging or keyboard adjustment expands the exact quote and cannot cross the opposite endpoint', () => {
  const selected = { block_id: 'p1', start: 2, end: 4, quote: '正文' };
  const text = '前😀正文后文';
  assert.deepEqual(moveSelectionEdge(selected, text, 'start', 1), { block_id: 'p1', start: 1, end: 4, quote: '😀正文' });
  assert.deepEqual(moveSelectionEdge(selected, text, 'end', 6), { block_id: 'p1', start: 2, end: 6, quote: '正文后文' });
  assert.deepEqual(moveSelectionEdge(selected, text, 'start', 9), { block_id: 'p1', start: 3, end: 4, quote: '文' });
  assert.deepEqual(moveSelectionEdge(selected, text, 'end', -1), { block_id: 'p1', start: 2, end: 3, quote: '正' });
});

test('long press selects a Chinese character or a complete English word using model offsets', () => {
  const block = { id: 'p1', text: '前😀正文 word 后文', kind: 'paragraph', editable: true, protected: [] };
  assert.deepEqual(pressedSelection(block, 1), { block_id: 'p1', start: 1, end: 2, quote: '😀' });
  assert.deepEqual(pressedSelection(block, 2), { block_id: 'p1', start: 2, end: 3, quote: '正' });
  assert.deepEqual(pressedSelection(block, 7), { block_id: 'p1', start: 5, end: 9, quote: 'word' });
});

test('a stationary mouse hold starts a precise selection; movement and scroll cancel it', context => {
  context.mock.timers.enable({ apis: ['setTimeout'] });
  const block = { id: 'p1', text: '前😀正文', kind: 'paragraph', editable: true, protected: [] };
  const textNode: any = { data: block.text, length: block.text.length };
  const selected: any[] = [];
  const native = { removeAllRanges() {}, addRange() {} };
  const document = Object.assign(new EventTarget(), {
    caretRangeFromPoint: () => ({ startContainer: textNode, startOffset: 3 }),
    getSelection: () => native,
    createRange: () => ({ selectNodeContents() {}, setEnd() {}, setStart() {}, toString: () => '前😀' }),
    createTreeWalker: () => { let read = false; return { nextNode: () => { if (read) return null; read = true; return textNode; } }; },
  });
  const element: any = { dataset: { blockText: 'p1' }, ownerDocument: document, contains: (node: any) => node === textNode, closest: () => element };
  const root = Object.assign(new EventTarget(), { ownerDocument: document });
  const pointer = (type: string, x = 10) => {
    const event = Object.assign(new Event(type), { pointerType: 'mouse', pointerId: 1, button: 0, isPrimary: true, clientX: x, clientY: 10 });
    Object.defineProperty(event, 'target', { value: element });
    return event;
  };
  const dispose = observeMouseLongPress(root as any, () => [block], value => selected.push(value));
  try {
    root.dispatchEvent(pointer('pointerdown'));
    context.mock.timers.tick(449);
    assert.equal(selected.length, 0);
    context.mock.timers.tick(1);
    assert.deepEqual(selected[0], { block_id: 'p1', start: 2, end: 3, quote: '正' });
    document.dispatchEvent(pointer('pointerup'));
    root.dispatchEvent(pointer('pointerdown'));
    document.dispatchEvent(pointer('pointermove', 30));
    context.mock.timers.tick(500);
    assert.equal(selected.length, 1, 'normal text dragging must not also fire the long-press shortcut');
    root.dispatchEvent(pointer('pointerdown'));
    document.dispatchEvent(new Event('scroll'));
    context.mock.timers.tick(500);
    assert.equal(selected.length, 1, 'scrolling must not start a selection');
  } finally { dispose(); }
});
