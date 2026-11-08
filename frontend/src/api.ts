import { getLocale, registerMessageTranslations, translate, translateForLocale } from './i18n.ts';

export class HttpError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'HttpError';
    this.status = status;
  }
}

function registerErrorTranslations(payload: { error_translations?: Record<string, string> }) {
  const pair = payload?.error_translations;
  if (typeof pair?.['zh-CN'] === 'string' && typeof pair?.en === 'string') {
    registerMessageTranslations(pair['zh-CN'], pair.en);
  }
}

function httpFailure(status: number) {
  const source = translateForLocale('请求失败（{status}）', 'zh-CN', { status });
  registerMessageTranslations(source, translateForLocale('请求失败（{status}）', 'en', { status }));
  return translate(source);
}

async function request(path: string, options: RequestInit = {}): Promise<Response> {
  const headers = new Headers(options.headers);
  headers.set('Accept-Language', getLocale());
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  try {
    return await fetch(`/api${path}`, { ...options, headers });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new Error(translate('连接本地服务失败，请确认文澄正在运行。'));
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const requestedLocale = getLocale();
  const response = await request(path, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    registerErrorTranslations(payload);
    throw new HttpError(payload.error ? translate(payload.error) : httpFailure(response.status), response.status);
  }
  const payload = await response.json();
  registerErrorTranslations(payload);
  // Refresh localized metadata after an in-flight language switch. Mutations
  // must run only once: refresh their resulting resource with a read request.
  if (requestedLocale !== getLocale()) {
    if (!options.method || options.method.toUpperCase() === 'GET') return api<T>(path, options);
    if (payload && typeof payload.id === 'string' && Array.isArray(payload.blocks) && Array.isArray(payload.annotations)) {
      return api<T>(`/projects/${encodeURIComponent(payload.id)}`, { signal: options.signal });
    }
    if (payload?.providers && payload?.config) return api<T>('/providers', { signal: options.signal });
  }
  return payload;
}

export function post<T>(path: string, body: unknown = {}): Promise<T> {
  return api<T>(path, { method: 'POST', body: JSON.stringify(body) });
}

export async function download(path: string, filename: string): Promise<void> {
  const response = await request(path);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    registerErrorTranslations(error);
    throw new Error(error.error ? translate(error.error) : translate('下载失败，请重试'));
  }
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
