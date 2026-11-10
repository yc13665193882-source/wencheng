#!/usr/bin/env node
// Read-only directory check. Does not install skills or send telemetry.
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';

const source = 'yc13665193882-source/wencheng';
const skill = 'wencheng';
const args = process.argv.slice(2);
if (args.length && (args.length !== 2 || args[0] !== '--output')) {
  console.log(JSON.stringify({ error: 'Usage: node scripts/check_skills_directory.mjs [--output path.json]' }));
  process.exit(1);
}

async function get(url) {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(25000) });
    return {
      url: String(url),
      finalUrl: response.url,
      httpStatus: response.status,
      ok: response.ok,
      headers: Object.fromEntries(['content-type', 'date', 'age', 'x-vercel-cache']
        .map((name) => [name, response.headers.get(name)])),
      body: await response.text(),
    };
  } catch (error) {
    return {
      url: String(url), httpStatus: null, ok: false,
      error: { message: error.message, code: error.cause?.code ?? error.name },
    };
  }
}

async function search(query) {
  const url = new URL('https://skills.sh/api/search');
  url.search = new URLSearchParams({ q: query }).toString();
  const response = await get(url);
  const result = { query, ...response, state: 'error', entries: [] };
  if (!response.ok) return result;
  try {
    result.payload = JSON.parse(response.body);
  } catch {
    result.error = { message: 'Search returned invalid JSON.' };
    return result;
  }
  if (!Array.isArray(result.payload.skills)) {
    result.error = { message: 'Search response has no skills array.' };
    return result;
  }
  result.entries = result.payload.skills.filter((entry) =>
    typeof entry?.source === 'string' && entry.source.toLowerCase() === source
    && entry.skillId === skill);
  result.state = result.entries.length ? 'found' : 'not_found';
  return result;
}

function textFromHtml(html) {
  const entities = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', middot: '·', rsquo: '’' };
  return html.replace(/<[^>]*>/g, ' ')
    .replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (entity, code) => {
      if (!code.startsWith('#')) return entities[code.toLowerCase()] ?? entity;
      const point = code[1].toLowerCase() === 'x' ? parseInt(code.slice(2), 16) : Number(code.slice(1));
      return point <= 0x10ffff ? String.fromCodePoint(point) : entity;
    })
    .replace(/\s+/g, ' ').trim();
}

async function detail() {
  const response = await get(`https://www.skills.sh/${source}/${skill}`);
  const result = { ...response, state: 'unknown', reason: 'request_failed' };
  if (!response.ok) return result;
  // Ignore scripts/React payloads: their text is not rendered skill content.
  const rendered = response.body.replace(/<(script|style|noscript)\b[^>]*>[\s\S]*?<\/\1>/gi, '')
    .replace(/<!--[\s\S]*?-->/g, '');
  result.title = textFromHtml(rendered.match(/<title\b[^>]*>([\s\S]*?)<\/title>/i)?.[1] ?? '');
  const main = rendered.match(/<main\b[^>]*>([\s\S]*?)<\/main>/i)?.[1];
  if (!main) return { ...result, reason: 'no_rendered_main' };
  result.mainText = textFromHtml(main);
  result.headings = [...main.matchAll(/<h1\b[^>]*>([\s\S]*?)<\/h1>/gi)]
    .map((match) => textFromHtml(match[1]));
  const missingHeading = result.headings.find((heading) =>
    /^wencheng\s+isn[’']t available in this repository\.?$/i.test(heading));
  if (missingHeading) return { ...result, state: 'missing', reason: 'catalog_missing_heading', evidence: missingHeading };
  if (/\bNo SKILL\.md available\b/i.test(result.mainText)) {
    return { ...result, state: 'missing', reason: 'skill_content_missing', evidence: 'No SKILL.md available' };
  }
  // Verified against the current skill's rendered Markdown heading, not its
  // document title (the catalog 404 page has the same document title).
  const contentHeading = result.headings.find((heading) => /^文澄\s*·\s*Wencheng$/i.test(heading));
  if (result.headings.some((heading) => heading.toLowerCase() === skill) && contentHeading) {
    return { ...result, state: 'loaded', reason: 'rendered_skill_heading', evidence: contentHeading };
  }
  return { ...result, reason: 'unrecognized_rendered_content' };
}

const [english, chinese, page] = await Promise.all([search('wencheng'), search('文澄'), detail()]);
const report = { checkedAt: new Date().toISOString(), source, skill, searches: [english, chinese], detail: page };
const summary = {
  checkedAt: report.checkedAt, source,
  searches: report.searches.map(({ query, url, httpStatus, state, entries, payload, error }) => ({
    query, url, httpStatus, state, returnedCount: payload?.count ?? null, entries, ...(error && { error }),
  })),
  detail: {
    url: page.url, httpStatus: page.httpStatus, state: page.state, reason: page.reason,
    ...(page.title && { title: page.title }), ...(page.evidence && { evidence: page.evidence }),
    ...(page.error && { error: page.error }),
  },
};
if (args.length) {
  try {
    const output = resolve(args[1]);
    await mkdir(dirname(output), { recursive: true });
    await writeFile(output, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
    summary.output = output;
  } catch (error) {
    summary.outputError = error.message;
  }
}
console.log(JSON.stringify(summary, null, 2));
// Missing is a valid observation; transport/schema failures are check errors.
if (report.searches.some((result) => result.state === 'error') || !page.ok || summary.outputError) process.exitCode = 1;
