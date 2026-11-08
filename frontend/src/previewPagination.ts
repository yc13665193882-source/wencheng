export type PageMeasurement = { declaredHeight: number; renderedHeight: number };
export type PaginationAssessment = { flowing: boolean; missingCachedBreaks: boolean; oversizedPages: number; unmeasuredPages: number };

/** HTML blocks are not Word pages when pagination evidence or page fit is absent. */
export function assessPreviewPagination(pages: PageMeasurement[], cachedBreaks: number): PaginationAssessment {
  const oversizedPages = pages.filter(page => page.declaredHeight > 0
    && page.renderedHeight > page.declaredHeight + Math.max(12, page.declaredHeight * 0.02)).length;
  const unmeasuredPages = pages.filter(page => !(page.declaredHeight > 0) || !(page.renderedHeight > 0)).length;
  const missingCachedBreaks = cachedBreaks === 0;
  return { flowing: !pages.length || missingCachedBreaks || oversizedPages > 0 || unmeasuredPages > 0,
    missingCachedBreaks, oversizedPages, unmeasuredPages };
}

export function measurePreviewPagination(container: HTMLElement): PaginationAssessment {
  const root = container.querySelector('[data-wc-cached-breaks]');
  const pages = Array.from(container.querySelectorAll<HTMLElement>('section.wc-docx'));
  return assessPreviewPagination(pages.map(page => ({
    declaredHeight: parseFloat(getComputedStyle(page).minHeight),
    renderedHeight: page.getBoundingClientRect().height,
  })), Number(root?.getAttribute('data-wc-cached-breaks') || 0));
}
