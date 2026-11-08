import { useLayoutEffect, useRef, useState, type RefObject, type PointerEvent as ReactPointerEvent } from 'react';
import type { Block, Selection } from './types';
import { useI18n } from './i18n';
import { moveDocumentSelectionEdge, paragraphRange, selectionPointAtCoordinates, selectionSlices, showDocumentSelection, stepDocumentSelectionEdge, type SelectionPoint } from './textSelection';

type Rect = { left: number; top: number; width: number; height: number };
type Edge = 'start' | 'end';

export function TextSelectionOverlay({ root, selection, blocks, onSelect }: {
  root: RefObject<HTMLElement | null>; selection: Selection | null; blocks: Block[];
  onSelect: (selection: Selection) => void;
}) {
  const { t } = useI18n();
  const [rects, setRects] = useState<Rect[]>([]);
  const [endpoints, setEndpoints] = useState<{ start: Rect; end: Rect } | null>(null);
  const drag = useRef<{ pointerId: number; edge: Edge; dx: number; dy: number } | null>(null);
  const current = useRef({ selection, blocks, onSelect });
  current.current = { selection, blocks, onSelect };

  useLayoutEffect(() => {
    const paper = root.current;
    if (!paper) return;
    const slices = selection ? selectionSlices(selection, blocks) : [];
    if (!selection || !slices.length) {
      setRects([]);
      setEndpoints(null);
      const native = paper.ownerDocument.getSelection();
      if (native?.anchorNode && paper.contains(native.anchorNode)) native.removeAllRanges();
      return;
    }
    const elements = slices.map(slice => paper.querySelector<HTMLElement>(`[data-block-text="${slice.block.id}"]`));
    if (elements.some(element => !element)) return;
    const measure = () => {
      const origin = paper.getBoundingClientRect();
      const relative = (rect: DOMRect): Rect => ({ left: rect.left - origin.left, top: rect.top - origin.top, width: rect.width, height: rect.height || 24 });
      const lines = slices.flatMap((slice, index) => {
        const range = paragraphRange(elements[index]!, slice.start, slice.end);
        return range ? Array.from(range.getClientRects()).filter(rect => rect.width > 0 && rect.height > 0) : [];
      });
      const unique = new Map(lines.map(rect => [`${rect.x}:${rect.y}:${rect.width}:${rect.height}`, relative(rect)]));
      setRects(Array.from(unique.values()));
      const endpoint = (index: number, offset: number): Rect => {
        const element = elements[index]!;
        const caret = paragraphRange(element, offset, offset)?.getClientRects()[0];
        if (caret?.height) return { ...relative(caret), width: 0 };
        return { ...relative(element.getBoundingClientRect()), width: 0 };
      };
      setEndpoints({ start: endpoint(0, selection.start), end: endpoint(elements.length - 1, selection.end) });
    };
    measure();
    const observer = new ResizeObserver(measure);
    elements.forEach(element => observer.observe(element!));
    window.addEventListener('resize', measure);
    return () => { observer.disconnect(); window.removeEventListener('resize', measure); };
  }, [root, selection, blocks]);

  const update = (next: Selection) => {
    const { onSelect: select } = current.current;
    if (root.current) showDocumentSelection(root.current, next);
    select(next);
  };

  const moveEdge = (edge: Edge, point: SelectionPoint) => {
    const { selection: selected, blocks: currentBlocks } = current.current;
    if (selected) update(moveDocumentSelectionEdge(selected, currentBlocks, edge, point));
  };

  const startDrag = (event: ReactPointerEvent<HTMLButtonElement>, edge: Edge, rect: Rect) => {
    event.preventDefault();
    event.stopPropagation();
    const origin = root.current?.getBoundingClientRect();
    if (!origin) return;
    const x = origin.left + rect.left + (edge === 'end' ? rect.width : 0);
    const y = origin.top + rect.top + rect.height / 2;
    drag.current = { pointerId: event.pointerId, edge, dx: event.clientX - x, dy: event.clientY - y };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const move = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const active = drag.current;
    if (!active || active.pointerId !== event.pointerId || !root.current) return;
    event.preventDefault();
    const point = selectionPointAtCoordinates(root.current, event.clientX - active.dx, event.clientY - active.dy);
    if (point) moveEdge(active.edge, point);
  };

  const stop = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (drag.current?.pointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };

  if (!selection || !endpoints) return null;
  return <div className="text-selection-overlay">
    {rects.map((rect, index) => <span key={index} aria-hidden="true" className="text-selection-highlight" style={rect} />)}
    {(['start', 'end'] as const).map(edge => {
      const rect = endpoints[edge];
      return <button key={edge} type="button" className={`text-selection-handle ${edge}`}
        aria-label={t(edge === 'start' ? '调整选区起点' : '调整选区终点')}
        title={t('拖动调整范围，也可聚焦后按左右方向键逐字调整')}
        style={{ left: rect.left + (edge === 'end' ? rect.width - 2 : -26), top: rect.top + rect.height - 2 }}
        onPointerDown={event => startDrag(event, edge, rect)} onPointerMove={move}
        onPointerUp={stop} onPointerCancel={stop} onLostPointerCapture={() => { drag.current = null; }}
        onClick={event => event.stopPropagation()}
        onKeyDown={event => {
          if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
          event.preventDefault();
          event.stopPropagation();
          update(stepDocumentSelectionEdge(selection, blocks, edge, event.key === 'ArrowLeft' ? -1 : 1));
        }}><span aria-hidden="true" /></button>;
    })}
  </div>;
}
