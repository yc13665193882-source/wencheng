"""Small, explainable writing checks. Findings are suggestions, never edits."""
from __future__ import annotations

import re


RULES = [
    {"id": "empty-emphasis", "category": "空泛强调", "pattern": r"值得注意的是[，,：:]?|需要强调的是[，,：:]?|毋庸置疑[，,]?|不言而喻[，,]?|不难发现[，,]?",
     "reason": "此处可能只是在提示读者注意，没有增加论述内容。", "instruction": "检查这个提示语是否必要；若没有承担转折或限定作用，删去提示语并保持后文原意。"},
    {"id": "empty-emphasis-en", "category": "空泛强调", "pattern": r"\b(?:It is (?:important|worthwhile|worth noting|crucial|essential) to (?:note|mention|emphasize) that|It is worth noting that|Needless to say|It goes without saying that)\b[, :]?",
     "reason": "开场强调可能可直接由后面的事实替代。", "instruction": "Remove the metadiscursive lead-in if it adds no qualification; preserve the proposition and its evidence."},
    {"id": "rule-restatement", "category": "规则复述", "pattern": r"(?:我[们]?将|本文将|以下内容将|本回答将)(?:严格)?(?:遵循|遵守|按照|依据)(?:你|您|上述|既定|所设定|本次|要求|规则|原则)[^。！？\n]{0,65}[。！？]?",
     "reason": "这句话可能在汇报遵守写作约定，适合从正文移到工作说明。", "instruction": "判断它是否只是复述对话约定；如果是，删除该工作说明。若描述真实研究方法或规范依据则保留。"},
    {"id": "rule-restatement-en", "category": "规则复述", "pattern": r"\b(?:As (?:you )?requested|Following your instructions|In accordance with your (?:instructions|requirements)|I (?:will|have) (?:strictly )?(?:follow|followed|adhere to|adhered to) your)[^.!?\n]{0,90}[.!?]?",
     "reason": "这可能是对话中的执行说明，不属于文档正文。", "instruction": "Remove conversational compliance reporting while retaining any substantive content in the sentence."},
    {"id": "evidence-assertion", "category": "依据复述", "pattern": r"(?:以上|上述|所有|本段|本文)(?:内容|结论|分析|论述|观点)(?:均|都)?(?:有据可依|有充分依据|有据可查|基于真实可靠的(?:资料|来源|依据))[^。！？\n]{0,30}[。！？]?",
     "reason": "笼统声明有依据，可能重复已有引文或分析。", "instruction": "核对是否已有明确证据；若只是重复宣称有依据，删去该声明，保留真实引用与证据强度。"},
    {"id": "evidence-assertion-en", "category": "依据复述", "pattern": r"\b(?:All (?:of )?(?:the |these )?(?:claims|statements|conclusions)|The above (?:analysis|conclusions)) (?:are|is) (?:fully |well-)?(?:supported by (?:reliable |credible )?(?:sources|evidence)|evidence-based)\b[^.!?\n]{0,35}[.!?]?",
     "reason": "概括性证据声明可能重复实际的引文和论证。", "instruction": "Keep the actual citations and evidence; remove a redundant blanket assurance if it adds no information."},
    {"id": "formulaic-contrast", "category": "机械对照", "pattern": r"这不仅仅?是[^。！？\n]{1,50}[，,]更是[^。！？\n]{1,60}[。！？]?|这不是[^。！？\n]{1,45}[，,]而是[^。！？\n]{1,60}[。！？]?",
     "reason": "对照句可能在制造没有必要的对立，需要结合语义检查。", "instruction": "检查对照两端是否真有区别；仅在对立空泛时改为直接陈述，保留有意义的比较。"},
    {"id": "formulaic-contrast-en", "category": "机械对照", "pattern": r"\b(?:This|It) (?:is|isn't|is not) (?:not )?(?:just|merely|only|about)\b[^.!?\n]{1,80}\b(?:but|it's about|it is about)\b[^.!?\n]{1,80}[.!?]?",
     "reason": "成套对照可能只有修辞作用，也可能是真实区别。", "instruction": "Retain a meaningful distinction; otherwise state the positive claim directly without rhetorical contrast."},
]


def _protected(block: dict, start: int, end: int) -> bool:
    for span in block.get("protected", []):
        a, b = span.get("start", 0), span.get("end", 0)
        if a == b:
            if start <= a < end:
                return True
        elif start < b and end > a:
            return True
    return False


def scan(blocks: list[dict], settings: dict | None = None) -> list[dict]:
    settings = settings or {}
    disabled = set(settings.get("disabled_rules", []))
    findings = []
    seen_sentences: dict[str, tuple[str, int]] = {}
    for block in blocks:
        if not block.get("editable", True):
            continue
        text = block.get("text", "")
        occupied: list[tuple[int, int]] = []
        for rule in RULES:
            if rule["id"] in disabled:
                continue
            for match in re.finditer(rule["pattern"], text, flags=re.IGNORECASE):
                start, end = match.span()
                if _protected(block, start, end) or any(start < b and end > a for a, b in occupied):
                    continue
                occupied.append((start, end))
                findings.append({"block_id": block["id"], "start": start, "end": end,
                                 "quote": text[start:end], "category": rule["category"],
                                 "instruction": rule["instruction"], "reason": rule["reason"], "rule_id": rule["id"]})
        if "repeated-sentence" in disabled:
            continue
        # Exact repeated sentences are more explainable than a fake semantic similarity score.
        for match in re.finditer(r"[^。！？.!?\n]+[。！？.!?]?", text):
            raw = match.group()
            quote = raw.strip()
            start = match.start() + len(raw) - len(raw.lstrip())
            end = start + len(quote)
            normalized = re.sub(r"\s+", " ", quote).casefold()
            if len(normalized) < 20 or _protected(block, start, end):
                continue
            previous = seen_sentences.get(normalized)
            if previous and not any(start < b and end > a for a, b in occupied):
                findings.append({"block_id": block["id"], "start": start, "end": end,
                                 "quote": quote, "category": "重复表达", "rule_id": "repeated-sentence",
                                 "reason": "前文已有相同句子；检查是否为必要复现。",
                                 "instruction": "结合段落用途检查重复；若没有新增信息则删除或合并，保留必要的定义、引文和结果复述。"})
            seen_sentences.setdefault(normalized, (block["id"], start))
    return findings
