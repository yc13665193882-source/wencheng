import assert from 'node:assert/strict';
import test from 'node:test';
import { assessPreviewPagination } from '../src/previewPagination.ts';
import { jumpToProofPage, proofPageSize, proofPageUrl, proofState } from '../src/proof.ts';
import type { ProofMetadata } from '../src/proof.ts';

test('the observed 42-page Chinese paper rendered as four blocks is classified as flowing', () => {
  const pages = [1122, 1122, 1122, 30715].map(renderedHeight => ({ declaredHeight: 1122, renderedHeight }));
  const result = assessPreviewPagination(pages, 0);
  assert.equal(result.flowing, true);
  assert.equal(result.oversizedPages, 1);
  assert.equal(result.missingCachedBreaks, true);
  // Oversized pages must be caught even when the package contains stale break caches.
  assert.equal(assessPreviewPagination(pages, 3).flowing, true);
});

test('38 page-sized English blocks with stored breaks remain eligible for reference page numbering', () => {
  const pages = Array.from({ length: 38 }, () => ({ declaredHeight: 1056, renderedHeight: 1056 }));
  assert.equal(assessPreviewPagination(pages, 37).flowing, false);
  assert.equal(assessPreviewPagination(pages, 0).flowing, true);
  assert.equal(assessPreviewPagination([{ declaredHeight: 0, renderedHeight: 1056 }], 37).flowing, true);
});

const proof: ProofMetadata = { exists: true, stale: false, pages: [{ number: 1, width: 1240, height: 1754 }],
  docx_sha256: 'original', current_docx_sha256: 'original', filename: 'word.pdf', created_at: '2026-11-04T12:00:00Z' };

test('proof cannot be shown as current before refreshing its binding after a document version change', () => {
  assert.equal(proofState(proof, 7, 7), 'current');
  assert.equal(proofState(proof, 7, 8), 'checking');
  assert.equal(proofState({ ...proof, current_docx_sha256: 'edited' }, 8, 8), 'stale');
  assert.equal(proofState({ ...proof, stale: true }, 8, 8), 'stale');
  assert.equal(proofState({ ...proof, exists: false }, 8, 8), 'missing');
});

test('replacement proofs get distinct image URLs and physical sizes only come from PDF points', () => {
  const replaced = { ...proof, created_at: '2026-11-04T12:01:00Z' };
  assert.notEqual(proofPageUrl('p1', 1, proof), proofPageUrl('p1', 1, replaced));
  assert.notEqual(proofPageUrl('p1', 1, proof), proofPageUrl('p1', 1, proof, 1));
  assert.equal(proofPageSize({ number: 1, width: 1240, height: 1754, width_pt: 595.276, height_pt: 841.89 }), '210.0 × 297.0 mm');
  assert.equal(proofPageSize(proof.pages[0]), '图像 1240 × 1754 px');
});

test('long proof navigation positions the target in the document viewport immediately and repeatably', () => {
  const requests: ScrollToOptions[] = [];
  const viewport = { scrollTop: 51181.332, scrollLeft: 0, clientTop: 0,
    getBoundingClientRect: () => ({ top: 150 }),
    scrollTo(options: ScrollToOptions) { requests.push(options); this.scrollTop = options.top!; },
  };
  let pageTop = 8404;
  const page = { closest: () => viewport, getBoundingClientRect: () => ({ top: pageTop }) };
  jumpToProofPage(page as any);
  assert.deepEqual(requests[0], { top: 59421.332, left: 0, behavior: 'instant' });
  // Repeating the command after arriving must preserve the same destination.
  pageTop = 164;
  jumpToProofPage(page as any);
  assert.deepEqual(requests[1], requests[0]);
  jumpToProofPage(null);
  assert.equal(requests.length, 2);
});
