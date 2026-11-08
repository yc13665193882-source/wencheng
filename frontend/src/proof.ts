export type ProofPage = { number: number; width: number; height: number; width_pt?: number; height_pt?: number };
export type ProofMetadata = {
  exists: boolean; stale: boolean; pages: ProofPage[];
  docx_sha256: string | null; current_docx_sha256: string;
  filename: string | null; created_at: string | null;
};

export function proofState(proof: ProofMetadata | null, checkedVersion: number | null, currentVersion: number) {
  if (!proof || checkedVersion !== currentVersion) return 'checking';
  if (!proof.exists) return 'missing';
  return proof.stale || !proof.docx_sha256 || proof.docx_sha256 !== proof.current_docx_sha256 ? 'stale' : 'current';
}

export function proofPageUrl(projectId: string, page: number, proof: ProofMetadata, retry = 0) {
  const version = `${proof.created_at || ''}:${proof.docx_sha256 || ''}:${retry}`;
  return `/api/projects/${encodeURIComponent(projectId)}/proof/pages/${page}?v=${encodeURIComponent(version)}`;
}

export function proofPageSize(page: ProofPage) {
  if (page.width_pt && page.height_pt) {
    return `${(page.width_pt * 25.4 / 72).toFixed(1)} × ${(page.height_pt * 25.4 / 72).toFixed(1)} mm`;
  }
  return translate('图像 {width} × {height} px', { width: page.width, height: page.height });
}

/** Jump only the document viewport; long smooth scrolls can be interrupted by image loading. */
export function jumpToProofPage(page: HTMLElement | null) {
  const viewport = page?.closest<HTMLElement>('.document-scroll');
  if (!page || !viewport) return;
  const top = viewport.scrollTop + page.getBoundingClientRect().top
    - viewport.getBoundingClientRect().top - viewport.clientTop - 14;
  viewport.scrollTo({ top: Math.max(0, top), left: viewport.scrollLeft, behavior: 'instant' });
}
import { translate } from './i18n.ts';

