import { useSyncExternalStore } from 'react';
import { appMessages, appSingularMessages } from './i18nApp.ts';
import { componentMessages } from './i18nMessages.ts';

export type Locale = 'zh-CN' | 'en';
export type TranslationParams = Record<string, string | number>;
export const localeStorageKey = 'wencheng.locale';
const messages: Record<string, string> = { ...componentMessages, ...appMessages };
const originalMessages = Object.fromEntries(Object.entries(messages).map(([source, translated]) => [translated, source]));
const listeners = new Set<() => void>();
const normalizeLocale = (value: string | null): Locale => value === 'en' ? 'en' : 'zh-CN';
let locale: Locale = (() => {
  try { return normalizeLocale(globalThis.localStorage?.getItem(localeStorageKey) || null); }
  catch { return 'zh-CN'; }
})();

export function getLocale(): Locale { return locale; }

/** Register paired service messages without translating arbitrary user text. */
export function registerMessageTranslations(source: string, english: string) {
  if (!source || !english) return;
  messages[source] = english;
  originalMessages[english] = source;
}

export function translateForLocale(source: string, targetLocale: Locale, params?: TranslationParams): string {
  const original = Object.hasOwn(messages, source) ? source : Object.hasOwn(originalMessages, source) ? originalMessages[source] : source;
  const singular = targetLocale === 'en' && Number(params?.count) === 1 && Object.hasOwn(appSingularMessages, original);
  const template = singular ? appSingularMessages[original] : targetLocale === 'en' && Object.hasOwn(messages, original) ? messages[original] : original;
  return template.replace(/\{(\w+)\}/g, (placeholder, name: string) => params && Object.hasOwn(params, name) ? String(params[name]) : placeholder);
}

export function translate(source: string, params?: TranslationParams): string {
  return translateForLocale(source, locale, params);
}

function updateDocumentLanguage() {
  if (typeof document === 'undefined') return;
  document.documentElement.lang = locale;
  document.title = translate('文澄 · 文档审阅工作台');
}

export function setLocale(next: Locale) {
  if (next !== 'en' && next !== 'zh-CN') return;
  locale = next;
  try { globalThis.localStorage?.setItem(localeStorageKey, next); } catch { /* Session-only language remains available. */ }
  updateDocumentLanguage();
  listeners.forEach(listener => listener());
}

export function initializeI18n() {
  updateDocumentLanguage();
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
};

export function useI18n() {
  const current = useSyncExternalStore(subscribe, getLocale, () => 'zh-CN' as Locale);
  return { locale: current, setLocale, t: translate };
}

if (typeof window !== 'undefined') window.addEventListener('storage', event => {
  if (event.key !== localeStorageKey) return;
  locale = normalizeLocale(event.newValue);
  updateDocumentLanguage();
  listeners.forEach(listener => listener());
});
