import { translate, translateForLocale, type Locale } from './i18n.ts';

export const protectionLabels: Record<string, string> = {
  equation: '公式', math: '公式', formula: '公式', field: '域与交叉引用', footnote: '脚注', endnote: '尾注',
  reference: '参考文献', references: '参考文献', bibliography: '参考文献', revision: '已有修订', comment: '批注边界',
  drawing: '图片与图形', object: '嵌入对象', hyperlink: '超链接', content_control: '内容控件',
  'content-control': '内容控件', 'text-box': '文本框', citation: '引文', symbol: '特殊符号',
  bookmark: '书签边界', layout: '分页与分栏', structure: '复杂文档结构',
};

/** Resolve at render time so protection names follow the selected interface language. */
export function protectionLabel(kind: string) {
  return translate(protectionLabels[kind] || kind);
}

/** Only complete generated tokens qualify; their canonical text remains the selection backing. */
export function protectedPlaceholderDisplay(text: string, kind: string, locale: Locale): string | null {
  if (kind === 'formula') {
    if (text === '〔公式〕') return translateForLocale('〔公式〕', locale);
    const formula = /^〔公式：([\s\S]+)〕$/.exec(text);
    return formula ? translateForLocale('〔公式：{notation}〕', locale, { notation: formula[1] }) : null;
  }
  if (kind === 'footnote' || kind === 'endnote') {
    const reference = (kind === 'footnote' ? /^〔脚注(-?\d*)〕$/ : /^〔尾注(-?\d*)〕$/).exec(text);
    if (!reference || reference[1] === '-') return null;
    const label = kind === 'footnote' ? (reference[1] ? '〔脚注{number}〕' : '〔脚注〕') : (reference[1] ? '〔尾注{number}〕' : '〔尾注〕');
    return translateForLocale(label, locale, { number: reference[1] });
  }
  if (kind === 'object' && text === '〔图形〕') return translateForLocale('〔图形〕', locale);
  if (kind === 'symbol' && text === '〔符号〕') return translateForLocale('〔符号〕', locale);
  return null;
}
