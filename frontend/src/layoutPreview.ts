import type { renderAsync } from 'docx-preview';

let renderSequence = 0;

/** Render into detached containers so a slow, obsolete version cannot alter the page. */
export async function renderLatestPreview(
  data: Blob, bodyTarget: HTMLElement, styleTarget: HTMLElement,
  isCurrent: () => boolean, renderer: typeof renderAsync,
): Promise<(() => void) | null> {
  const body = bodyTarget.ownerDocument.createElement('div');
  const styles = bodyTarget.ownerDocument.createElement('div');
  // docx-preview registers comment Highlights globally, even for detached DOM.
  // Per-render names prevent an obsolete render from replacing current highlights.
  const className = `wc-preview-${++renderSequence}`;
  const dispose = () => globalThis.CSS?.highlights?.delete(`${className}-comments`);
  try {
    await renderer(data, body, styles, {
      className, inWrapper: true, ignoreLastRenderedPageBreak: false,
      // Read the final text: insertions remain, deletions must not occupy layout space.
      renderChanges: false, renderComments: true, renderAltChunks: false,
      renderHeaders: true, renderFooters: true, renderFootnotes: true, renderEndnotes: true,
      useBase64URL: true,
    });
    if (!isCurrent()) { dispose(); return null; }
    body.querySelector(`.${className}-wrapper`)?.classList.add('wc-docx-wrapper');
    body.querySelectorAll(`section.${className}`).forEach(page => page.classList.add('wc-docx'));
    styleTarget.replaceChildren(...styles.childNodes);
    bodyTarget.replaceChildren(...body.childNodes);
    return dispose;
  } catch (error) {
    dispose();
    throw error;
  }
}
