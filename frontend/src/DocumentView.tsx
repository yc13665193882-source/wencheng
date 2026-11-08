import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, FileText, LoaderCircle, LockKeyhole, MessageSquarePlus, Table2 } from 'lucide-react';
import type { Annotation, Block, Project, Selection } from './types';
import { protectedPlaceholderDisplay, protectionLabel } from './protections';
import { useI18n } from './i18n';
import { renderLatestPreview } from './layoutPreview';
import { renderAdaptedDocx, updatePreviewPageFields } from './docxPreviewAdapter';
import { measurePreviewPagination } from './previewPagination';
import type { PaginationAssessment } from './previewPagination';
import { observeMouseLongPress, observeParagraphSelection, selectionSlices, showNativeSelection } from './textSelection';
import { TextSelectionOverlay } from './TextSelectionOverlay';

export function ReviewDocument({ project, selection, activeId, onSelect, onAnnotation, onInvalidSelection }: {
  project: Project; selection: Selection | null; activeId: string | null;
  onSelect: (value: Selection) => void; onAnnotation: (id: string) => void;
  onInvalidSelection: () => void;
}) {
  const { locale, t } = useI18n();
  const annotations = project.annotations.filter(a => a.status === 'pending' || a.status === 'suggested');
  const selectedSlices = selection ? selectionSlices(selection, project.blocks) : [];
  const paper = useRef<HTMLElement>(null);
  const callbacks = useRef({ project, onSelect, onInvalidSelection });
  callbacks.current = { project, onSelect, onInvalidSelection };
  useEffect(() => {
    if (!paper.current) return;
    const stopSelection = observeParagraphSelection(paper.current, () => callbacks.current.project.blocks,
      value => callbacks.current.onSelect(value), () => callbacks.current.onInvalidSelection());
    const stopLongPress = observeMouseLongPress(paper.current, () => callbacks.current.project.blocks,
      value => callbacks.current.onSelect(value));
    return () => { stopSelection(); stopLongPress(); };
  }, []);

  return <article ref={paper} className="document-paper" aria-label={t('文档结构审阅')}>
    <div className="paper-eyebrow"><FileText size={13} /> {t('文档正文')} <span>{t('结构审阅')}</span></div>
    {project.blocks.length === 0 && <div className="paper-empty">{t('文档还是空白的。使用“继续写作”开始生成正文。')}</div>}
    {project.blocks.map((block, index) => {
      const blockAnnotations = annotations.flatMap(annotation => {
        const slice = selectionSlices(annotation, project.blocks).find(part => part.block.id === block.id);
        return slice ? [{ ...annotation, start: slice.start, end: slice.end }] : [];
      });
      const isSelected = selectedSlices.some(part => part.block.id === block.id);
      const heading = block.kind === 'heading' || /heading|标题|title/i.test(block.style || '');
      return <section id={`block-${block.id}`} key={block.id} className={`document-block ${heading ? 'heading-block' : ''} ${block.kind === 'table-cell' ? 'table-block' : ''} ${isSelected ? 'selected-block' : ''}`}>
        <button className="block-number" title={t('选择第 {number} 段', { number: index + 1 })} aria-label={t('选择第 {number} 段', { number: index + 1 })} onClick={() => {
          const value = { block_id: block.id, start: 0, end: Array.from(block.text).length, quote: block.text };
          const element = paper.current?.querySelector<HTMLElement>(`[data-block-text="${block.id}"]`);
          if (element && block.text) showNativeSelection(element, value);
          onSelect(value);
        }}>{String(index + 1).padStart(2, '0')}</button>
        <div className="block-main">
          {block.kind === 'table-cell' && <div className="table-label"><Table2 size={12} /> {t('表格单元格')}</div>}
          <div data-block-text={block.id} className={`block-text ${heading ? 'heading-text' : ''}`}>
            <MarkedText block={block} annotations={blockAnnotations} activeId={activeId} onAnnotation={onAnnotation} />
          </div>
          {!block.text && <span className="empty-paragraph">{t('空段落')}</span>}
        </div>
        <div className="block-indicators">
          {block.protected?.length > 0 && <span title={t('受保护：{items}', { items: [...new Set(block.protected.map(range => protectionLabel(range.kind)))].join(locale === 'en' ? ', ' : '、') })}><LockKeyhole size={13} /></span>}
          {blockAnnotations.length > 0 && <button className="annotation-count" title={t('查看本段标记')} aria-label={t(blockAnnotations.length === 1 ? '查看本段 1 条标记' : '查看本段 {count} 条标记', { count: blockAnnotations.length })} onClick={() => onAnnotation(blockAnnotations[0].id)}><MessageSquarePlus size={12} />{blockAnnotations.length}</button>}
        </div>
      </section>;
    })}
    <TextSelectionOverlay root={paper} selection={selection} blocks={project.blocks} onSelect={onSelect} />
    <div className="paper-end"><span />{t('文档结束')}<span /></div>
  </article>;
}

function MarkedText({ block, annotations, activeId, onAnnotation }: {
  block: Block; annotations: Annotation[]; activeId: string | null; onAnnotation: (id: string) => void;
}) {
  const { locale, t } = useI18n();
  const chars = Array.from(block.text);
  const cuts = new Set([0, chars.length]);
  for (const a of [...annotations, ...(block.protected || [])]) {
    cuts.add(Math.max(0, Math.min(chars.length, a.start)));
    cuts.add(Math.max(0, Math.min(chars.length, a.end)));
  }
  const points = [...cuts].sort((a, b) => a - b);
  return <>{points.slice(0, -1).map((start, i) => {
    const end = points[i + 1];
    const text = chars.slice(start, end).join('');
    const annotation = annotations.find(a => a.start <= start && a.end >= end);
    const protectedRange = block.protected?.find(a => a.start <= start && a.end >= end);
    if (annotation) return <mark key={start} className={annotation.id === activeId ? 'active-mark' : ''} title={annotation.instruction} onClick={() => {
      // A drag or long press ending on a mark selects text; it must not open a different panel.
      const native = window.getSelection();
      if (native && !native.isCollapsed) return;
      onAnnotation(annotation.id);
    }}>{text}</mark>;
    if (protectedRange) {
      const display = start === protectedRange.start && end === protectedRange.end
        ? protectedPlaceholderDisplay(text, protectedRange.kind, locale) : null;
      const localizedPlaceholder = display !== null && display !== text;
      return <span key={start} className={`protected-text${localizedPlaceholder ? ' protected-placeholder' : ''}`}
        role={localizedPlaceholder ? 'img' : undefined}
        data-display={localizedPlaceholder ? display : undefined} aria-label={localizedPlaceholder ? display : undefined}
        title={t('受保护：{items}', { items: protectionLabel(protectedRange.kind) })}>{text}</span>;
    }
    return <span key={start}>{text}</span>;
  })}</>;
}

export function LayoutPreview({ project, onProof }: { project: Project; onProof: () => void }) {
  const { locale, t } = useI18n();
  const container = useRef<HTMLDivElement>(null);
  const styleContainer = useRef<HTMLDivElement>(null);
  const visibleProject = useRef('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [pagination, setPagination] = useState<PaginationAssessment | null>(null);
  useEffect(() => {
    let canceled = false;
    let dispose: (() => void) | null = null;
    let observer: ResizeObserver | null = null;
    let frame = 0;
    const controller = new AbortController();
    if (visibleProject.current !== project.id) {
      container.current?.replaceChildren();
      styleContainer.current?.replaceChildren();
      visibleProject.current = project.id;
    }
    setLoading(true);
    setError('');
    setPagination(null);
    const load = async () => {
      try {
        const response = await fetch(`/api/projects/${project.id}/export`, { signal: controller.signal });
        if (!response.ok) throw new Error('无法读取文档预览');
        const data = await response.blob();
        if (canceled || !container.current || !styleContainer.current) return;
        dispose = await renderLatestPreview(data, container.current, styleContainer.current, () => !canceled, renderAdaptedDocx);
        if (!canceled && container.current) {
          const measure = () => {
            if (canceled || !container.current) return;
            const result = measurePreviewPagination(container.current);
            updatePreviewPageFields(Array.from(container.current.querySelectorAll('section.wc-docx')), !result.flowing);
            setPagination(previous => JSON.stringify(previous) === JSON.stringify(result) ? previous : result);
          };
          frame = requestAnimationFrame(measure);
          observer = new ResizeObserver(measure);
          container.current.querySelectorAll('section.wc-docx').forEach(page => observer!.observe(page));
          void document.fonts.ready.then(measure);
          setLoading(false);
        }
      } catch (e) {
        if (!canceled) { setError(e instanceof Error ? e.message : '预览失败'); setLoading(false); }
      }
    };
    void load();
    return () => { canceled = true; controller.abort(); observer?.disconnect(); cancelAnimationFrame(frame); dispose?.(); };
  }, [project.id, project.version]);
  useEffect(() => {
    if (container.current && pagination) {
      updatePreviewPageFields(Array.from(container.current.querySelectorAll('section.wc-docx')), !pagination.flowing);
    }
  }, [locale, pagination]);
  return <div className="layout-preview">
    {pagination?.flowing ? <div className="preview-warning" role="status">
      <AlertTriangle size={18} />
      <div><strong>{t('流式参考 · 不可用作 Word 分页校验')}</strong>
        <p>{pagination.oversizedPages > 0 && t(pagination.oversizedPages === 1 ? '检测到 1 个内容块超过纸张高度。' : '检测到 {count} 个内容块超过纸张高度。', { count: pagination.oversizedPages })}{pagination.missingCachedBreaks && t('此 DOCX 没有 Word 自动分页缓存。')}{t('浏览器不会按内容重新分页，显示的内容块数量不是文档页数。页码保留原文件缓存。')}</p>
        <button className="button quiet compact" onClick={onProof}>{t('打开 Word 校样，核对真实分页')}</button>
      </div>
    </div> : <div className="preview-note">{t('HTML 版式参考 · 显示修订后的正文。')}{t(pagination ? '按文件中的分页标记呈现，字体与分页仍可能与 Word 不同。' : '正在检查分页与内容高度。')}{t('真实分页请查看“Word 校样”。宽页可横向滚动，精确选区请切换到“审阅”。')}</div>}
    {loading && <div className="preview-loading"><LoaderCircle className="spin" size={20} /> {t('正在呈现 DOCX…')}</div>}
    {error && <div className="inline-error" role="alert">{t(error)}</div>}
    <div ref={styleContainer} />
    <div ref={container} className="docx-renderer" />
  </div>;
}
