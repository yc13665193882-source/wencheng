import assert from 'node:assert/strict';
import test from 'node:test';
import { createJobPoller } from '../src/jobPolling.ts';
import { HttpError } from '../src/api.ts';
import { setLocale } from '../src/i18n.ts';
import type { Job, Project } from '../src/types.ts';

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const task = (status: Job['status'], progress = 1): Job => ({ status, progress, project_id: 'paper', ...(status === 'error' ? { error: 'Model failed after one paragraph' } : {}) });
const project = (version: number) => ({ id: 'paper', version, blocks: [], annotations: [] });

function observe() {
  const updates: { job: Job; project: Project }[] = [];
  const finished: Job[] = [];
  const interrupted: unknown[] = [];
  const fatal: unknown[] = [];
  const poller = createJobPoller('task', {
    onUpdate: (job, project) => updates.push({ job, project }),
    onFinished: job => finished.push(job),
    onInterrupted: error => interrupted.push(error),
    onFatal: error => fatal.push(error),
  });
  return { ...poller, updates, finished, interrupted, fatal };
}

test('temporary network and 5xx failures keep the same job until recovered final content arrives', async () => {
  const original = globalThis.fetch;
  const calls: string[] = [];
  const replies = [
    () => { throw new TypeError('Disconnected'); },
    () => json({ error: 'Server is restarting' }, 503),
    () => json(task('running', 1)), () => json(project(2)),
    () => json(task('done', 2)), () => json(project(3)),
  ];
  globalThis.fetch = async input => { calls.push(String(input)); return replies.shift()!(); };
  try {
    const poller = observe();
    await poller.poll();
    await poller.poll();
    assert.equal(poller.interrupted.length, 1, 'one message for the entire interruption');
    assert.equal(poller.finished.length, 0);
    assert.equal(poller.fatal.length, 0);
    await poller.poll();
    assert.equal(poller.updates[0].project.version, 2);
    await poller.poll();
    assert.equal(poller.updates[1].project.version, 3);
    assert.equal(poller.finished[0].status, 'done');
    await poller.poll();
    assert.equal(calls.length, 6, 'a completed job does not keep fetching');
    assert.equal(calls.filter(path => path.endsWith('/jobs/task')).length, 4);
  } finally { globalThis.fetch = original; }
});

test('a failed final project read is retried and still propagates the server task error', async () => {
  const original = globalThis.fetch;
  const replies = [
    () => json(task('error')), () => json({ error: 'Temporarily unavailable' }, 502),
    () => json(task('error')), () => json(project(2)),
  ];
  globalThis.fetch = async () => replies.shift()!();
  try {
    const poller = observe();
    await poller.poll();
    assert.equal(poller.finished.length, 0, 'retain tracking until the final saved content can be read');
    await poller.poll();
    assert.equal(poller.finished[0].status, 'error');
    assert.equal(poller.finished[0].error, 'Model failed after one paragraph');
    assert.equal(poller.updates[0].project.version, 2);
    assert.equal(poller.fatal.length, 0);
  } finally { globalThis.fetch = original; }
});

test('a missing job stops polling while HTTP 429 remains recoverable', async () => {
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => json({ error: 'Try later' }, ++calls === 1 ? 429 : 404);
  try {
    const poller = observe();
    await poller.poll();
    assert.equal(poller.interrupted.length, 1);
    await poller.poll();
    assert.ok(poller.fatal[0] instanceof HttpError);
    assert.equal((poller.fatal[0] as HttpError).status, 404);
    await poller.poll();
    assert.equal(calls, 2);
    assert.equal(poller.finished.length, 0);
  } finally { globalThis.fetch = original; }
});

test('effect cleanup discards an old locale response and the replacement poller resumes the same job', async () => {
  const original = globalThis.fetch;
  let resolveFirst!: (response: Response) => void;
  let calls = 0;
  globalThis.fetch = async () => ++calls === 1
    ? new Promise<Response>(resolve => { resolveFirst = resolve; })
    : calls < 4 ? json(task('done')) : json(project(2));
  try {
    setLocale('zh-CN');
    const before = observe();
    const inFlight = before.poll();
    await before.poll();
    assert.equal(calls, 1, 'overlapping interval ticks do not start another read');
    before.stop();
    setLocale('en');
    resolveFirst(json(task('done')));
    await inFlight;
    assert.equal(before.updates.length, 0);
    assert.equal(before.finished.length, 0);
    const after = observe();
    await after.poll();
    assert.equal(after.finished[0].status, 'done');
    assert.equal(after.updates[0].project.version, 2);
  } finally { globalThis.fetch = original; setLocale('zh-CN'); }
});
