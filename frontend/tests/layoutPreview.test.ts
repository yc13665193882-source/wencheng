import assert from 'node:assert/strict';
import test from 'node:test';
import { renderLatestPreview } from '../src/layoutPreview.ts';

function target() {
  const element = {
    childNodes: [] as string[],
    ownerDocument: { createElement: () => target() },
    replaceChildren(...children: string[]) { this.childNodes = children; },
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  return element;
}

test('obsolete asynchronous renders cannot replace current pages, styles or comment highlights', async () => {
  const body = target();
  const styles = target();
  const highlights = new Map<string, unknown>();
  const priorCSS = globalThis.CSS;
  Object.defineProperty(globalThis, 'CSS', { value: { highlights }, configurable: true });
  let finishOld!: () => void;
  const slow = new Promise<void>(resolve => { finishOld = resolve; });
  let oldCurrent = true;
  const renderer = async (data: any, stagedBody: any, stagedStyles: any, options: any) => {
    assert.equal(options.renderChanges, false, 'HTML preview must show the final text, without deleted text occupying space');
    if (data === 'old') await slow;
    stagedBody.childNodes = [data];
    stagedStyles.childNodes = [`style:${data}`];
    highlights.set(`${options.className}-comments`, data);
  };
  try {
    const obsolete = renderLatestPreview('old' as any, body as any, styles as any, () => oldCurrent, renderer);
    oldCurrent = false;
    const disposeCurrent = await renderLatestPreview('new' as any, body as any, styles as any, () => true, renderer);
    finishOld();
    assert.equal(await obsolete, null);
    assert.deepEqual(body.childNodes, ['new']);
    assert.deepEqual(styles.childNodes, ['style:new']);
    assert.deepEqual([...highlights.values()], ['new']);
    disposeCurrent?.();
    assert.equal(highlights.size, 0);
  } finally {
    Object.defineProperty(globalThis, 'CSS', { value: priorCSS, configurable: true });
  }
});

test('failed previews keep the last readable page and styles together', async () => {
  const body = target();
  const styles = target();
  body.childNodes = ['readable page'];
  styles.childNodes = ['readable style'];
  const renderer = async (_data: any, stagedBody: any) => {
    stagedBody.childNodes = ['partial page'];
    throw new Error('invalid document');
  };
  await assert.rejects(() => renderLatestPreview({} as Blob, body as any, styles as any, () => true, renderer), /invalid document/);
  assert.deepEqual(body.childNodes, ['readable page']);
  assert.deepEqual(styles.childNodes, ['readable style']);
});
