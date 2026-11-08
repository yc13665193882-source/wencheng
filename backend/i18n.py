"""Localize system-owned response fields, never document or user-authored text.

The stored Chinese messages remain canonical for CLI compatibility. HTTP language
selection only changes copies. Dynamic errors use anchored templates so arbitrary
model/API details are retained verbatim rather than guessed or translated.
"""
from __future__ import annotations

from copy import deepcopy
import re


MESSAGES = {
    '未命名文档': 'Untitled document',
    '结果文件不是有效的 UTF-8 JSON，请检查文件格式。': 'The result file is not valid UTF-8 JSON. Check its format.',
    '请求无效，请检查输入。': 'Invalid request. Check the input.',
    '此操作不被允许。': 'This operation is not allowed.',
    '请求的资源不存在。': 'The requested resource was not found.',
    '此接口不支持该请求方法。': 'This endpoint does not support that request method.',
    '上传文件过大，请选择 50 MB 以内的文件。': 'The upload is too large. Choose a file no larger than 50 MB.',
    '不支持此文件或请求格式。': 'This file or request format is not supported.',
    '服务处理请求失败。': 'The service could not process the request.',
    '仅允许本地文澄页面修改项目': 'Only the local Wencheng page can modify projects.',
    '需要 JSON 请求正文': 'A JSON request body is required.',
    'DOCX 解压后过大，请使用小于 250 MB 的文档': 'The expanded DOCX exceeds 250 MB. Choose a smaller document.',
    '文件不是有效 DOCX 文档': 'This file is not a valid DOCX document.',
    '标记不存在': 'Annotation not found.',
    'paragraphs 必须是字符串数组': 'paragraphs must be an array of strings.',
    '请选择 .docx 文件': 'Choose a .docx file.',
    '该标记还没有可应用的改稿': 'This annotation has no suggestion to apply.',
    '此标记无法再次生成建议': 'A new suggestion cannot be generated for this annotation.',
    '模型没有返回有效改稿': 'The model did not return a valid replacement.',
    '生成期间标记已改变，未写入旧建议': 'The annotation changed during generation. The outdated suggestion was not saved.',
    '已应用的修改请通过历史撤销': 'Use history to undo an applied change.',
    '该标记已经写入 Word 批注': 'This annotation has already been added as a Word comment.',
    '未知标记操作': 'Unknown annotation action.',
    '请等待当前 AI 任务结束后撤销': 'Wait for the current AI task to finish before undoing.',
    '请选择本机 Word 导出的 .pdf 校样文件。': 'Choose a .pdf proof exported from Word on this computer.',
    '结果文件项目编号不匹配，或缺少 results 数组': 'The result file has a different project ID or is missing the results array.',
    '标记或原文已改变，不能导入旧结果': 'The annotation or source text has changed. Outdated results cannot be imported.',
    '改稿必须是字符串': 'The replacement must be a string.',
    '请选择有效的 AI 接入方式': 'Choose a valid AI provider.',
    '此文档已有 AI 任务正在运行': 'An AI task is already running for this document.',
    '请输入文档要求或提纲': 'Enter the document requirements or an outline.',
    '请先添加修改标记或检查表达': 'Add an annotation or run the writing checks first.',
    '任务不存在，服务可能已重启': 'Task not found. The service may have restarted.',
    '前端尚未构建，请在项目目录运行 npm run build。': 'The frontend has not been built. Run npm run build in the project directory.',
    '项目编号无效': 'Invalid project ID.',
    '项目不存在': 'Project not found.',
    '没有可撤销的操作': 'There is nothing to undo.',
    'DOCX 缺少正文。': 'The DOCX document has no body.',
    '无法读取 DOCX，请选择未加密的 Word 文档。': 'Cannot read the DOCX. Choose an unencrypted Word document.',
    '无效的段落标识。': 'Invalid paragraph ID.',
    '段落已不存在，请刷新文档。': 'The paragraph no longer exists. Refresh the document.',
    '选区位置无效。': 'Invalid selection offsets.',
    '选区超出段落范围。': 'The selection extends beyond the paragraph.',
    '请选择有效文字。': 'Select a valid text range.',
    '跨段修改须位于连续正文或同一表格单元格内，不能跨越表格结构。': 'A multi-paragraph selection must stay within consecutive body paragraphs or one table cell.',
    '选区跨越分节符，请在同一节内修改。': 'The selection crosses a section break. Make the change within one section.',
    '原文已改变，请重新选择文字。': 'The source text has changed. Select the text again.',
    '选区位置必须是整数。': 'Selection offsets must be integers.',
    '原文已改变，请重新选择后再修改。': 'The source text has changed. Select it again before editing.',
    '该选区位于复杂结构中，暂不能局部修改。': 'This selection is inside a complex structure that does not support partial editing yet.',
    '修改内容必须是文本。': 'The replacement must be text.',
    '跨段修改不能越过表格或复杂文档结构。': 'A multi-paragraph edit cannot cross a table or a complex document structure.',
    '选区包含不可改写的文档元素。': 'The selection contains document elements that cannot be rewritten.',
    '标记边界不能位于文档对象内部。': 'Annotation boundaries cannot fall inside document objects.',
    '标记边界位于受保护结构中。': 'An annotation boundary falls inside a protected structure.',
    '批注内容不能为空。': 'A comment cannot be empty.',
    '选区位置已改变，请重新标记。': 'The selection has moved. Create a new annotation.',
    '此选区与已应用的修改重叠，请重新标记。': 'This selection overlaps an applied change. Create a new annotation.',
    '此选区与已应用的修改重叠或原文已改变，请重新标记。': 'This selection overlaps an applied change or its source text has changed. Create a new annotation.',
    'PDF 校样依赖未安装，请重新安装项目 requirements.txt 中的依赖。': 'PDF proof dependencies are missing. Install the dependencies in requirements.txt.',
    'PDF 校样记录无效，请重新上传。': 'The PDF proof record is invalid. Upload the proof again.',
    '无法读取 PDF 校样，请上传未加密且能正常打开的 PDF。': 'Cannot read the PDF proof. Upload an unencrypted PDF that opens correctly.',
    'PDF 校样不能为空，且不能超过 50 MB。': 'The PDF proof must not be empty or exceed 50 MB.',
    '文件不是有效 PDF 校样。': 'This file is not a valid PDF proof.',
    '尚未上传 PDF 校样。': 'No PDF proof has been uploaded.',
    'PDF 校样页码不存在。': 'The requested PDF proof page does not exist.',
    '本机 Codex': 'Local Codex',
    '本机 Claude Code': 'Local Claude Code',
    'OpenAI 兼容 API': 'OpenAI-compatible API',
    '已停止 AI 任务。': 'The AI task was stopped.',
    '模型未返回有效 JSON；未写入文档，请重试或更换模型。': 'The model did not return valid JSON. The document was not changed. Retry or choose another model.',
    '模型返回格式不符：需要 JSON 对象。': 'The model response must be a JSON object.',
    '未知的本机 AI 提供方。': 'Unknown local AI provider.',
    '模型调用失败': 'The model request failed.',
    'Claude 调用失败': 'The Claude request failed.',
    '请在终端检查登录状态。': 'Check the login status in a terminal.',
    'API 密钥环境变量名无效。': 'Invalid API key environment variable name.',
    '请先在 AI 设置中填写 API 模型名称。': 'Enter an API model name in AI settings first.',
    'API 地址需要完整的 http(s) URL，且不能在 URL 中包含凭证。': 'The API address must be a complete HTTP(S) URL without credentials in the URL.',
    '远程 API 地址请使用 HTTPS。': 'Use HTTPS for a remote API address.',
    'API 请求超时，请重试或缩小处理范围。': 'The API request timed out. Retry or use a smaller selection.',
    'API 未返回正文。': 'The API returned no text.',
    '请选择 Codex、Claude Code 或 OpenAI 兼容 API。': 'Choose Codex, Claude Code, or an OpenAI-compatible API.',
    '改写选区不能为空。': 'The text selection to rewrite cannot be empty.',
    '模型建议缺少 replacement 字符串；未写入文档。': 'The model suggestion is missing a replacement string. The document was not changed.',
    '模型建议包含新段落。当前选区修改需保留段落结构，请缩小范围后重试。': 'The suggestion contains new paragraphs. This selection must preserve its paragraph structure. Select a smaller range and retry.',
    '请填写写作需求或提纲。': 'Enter the writing requirements or an outline.',
    '模型返回的段落计划无效。': 'The model returned an invalid paragraph plan.',
    '模型返回了空段落。': 'The model returned an empty paragraph.',
    '更新文风设置': 'Updated writing preferences',
    '添加修改标记': 'Added an editing annotation',
    '应用改稿为 Word 修订': 'Applied a suggestion as a Word tracked change',
    '生成局部改写建议': 'Generated a rewrite suggestion',
    '拒绝建议': 'Rejected a suggestion',
    '写入 Word 批注': 'Added a Word comment',
    '导入聊天生成的改稿': 'Imported suggestions from chat',
    '写入 AI 生成段落': 'Added an AI-generated paragraph',
    '聊天写入新段落': 'Added a paragraph from chat',
    '用户标记': 'User annotation',
    '空泛强调': 'Empty emphasis',
    '规则复述': 'Repeated instructions',
    '依据复述': 'Repeated evidence assurances',
    '机械对照': 'Formulaic contrast',
    '重复表达': 'Repetition',
    '克制地改善表达，保留原意与正式文风。': 'Improve the wording conservatively while preserving the meaning and formal tone.',
    '此处可能只是在提示读者注意，没有增加论述内容。': 'This phrase may call for attention without adding substance.',
    '检查这个提示语是否必要；若没有承担转折或限定作用，删去提示语并保持后文原意。': 'Check whether this lead-in is needed. Remove it if it adds no transition or qualification, preserving the meaning that follows.',
    '开场强调可能可直接由后面的事实替代。': 'The introductory emphasis may be replaced by the facts that follow.',
    '这句话可能在汇报遵守写作约定，适合从正文移到工作说明。': 'This sentence may report compliance with writing instructions and belong in an editing note.',
    '判断它是否只是复述对话约定；如果是，删除该工作说明。若描述真实研究方法或规范依据则保留。': 'Check whether this merely repeats chat instructions. Remove that process note, but retain actual research methods or applicable standards.',
    '这可能是对话中的执行说明，不属于文档正文。': 'This may be a conversational process note rather than document content.',
    '笼统声明有依据，可能重复已有引文或分析。': 'A blanket assurance of evidence may repeat existing citations or analysis.',
    '核对是否已有明确证据；若只是重复宣称有依据，删去该声明，保留真实引用与证据强度。': 'Check for actual evidence. Remove a redundant assurance while preserving real citations and the strength of the evidence.',
    '概括性证据声明可能重复实际的引文和论证。': 'A general assurance of evidence may repeat the actual citations and argument.',
    '对照句可能在制造没有必要的对立，需要结合语义检查。': 'The contrast may introduce an unnecessary opposition. Check its meaning in context.',
    '检查对照两端是否真有区别；仅在对立空泛时改为直接陈述，保留有意义的比较。': 'Check whether the contrast describes a real distinction. Replace empty opposition with a direct statement, retaining meaningful comparisons.',
    '成套对照可能只有修辞作用，也可能是真实区别。': 'The formulaic contrast may be rhetorical or may describe a real distinction.',
    '前文已有相同句子；检查是否为必要复现。': 'An identical sentence appears earlier. Check whether the repetition is necessary.',
    '结合段落用途检查重复；若没有新增信息则删除或合并，保留必要的定义、引文和结果复述。': 'Check repetition in context. Remove or merge it if it adds no information, retaining necessary definitions, quotations, and restated results.',
}

# English-language checks originally stored English instructions. Both UI
# languages have translations, independent of the language of the document.
ENGLISH_RULE_INSTRUCTIONS = {
    'Remove the metadiscursive lead-in if it adds no qualification; preserve the proposition and its evidence.': '若开场提示语没有增加限定，删除它并保留论点与证据。',
    'Remove conversational compliance reporting while retaining any substantive content in the sentence.': '删除汇报遵守对话要求的说明，保留句子中的实质内容。',
    'Keep the actual citations and evidence; remove a redundant blanket assurance if it adds no information.': '保留真实引文与证据；若笼统保证没有新增信息，删除该保证。',
    'Retain a meaningful distinction; otherwise state the positive claim directly without rhetorical contrast.': '保留有意义的区别；否则直接陈述观点，去掉修辞性的对照。',
}

TASK_INSTRUCTIONS = '为每个标记生成完整选区的 replacement 和简短 reason。跨段选区作为一个整体修改，用换行分隔改稿段落，可以按要求合并或重新分段。保持 id 与 quote 不变。仅返回 {project_id, results:[{id,quote,replacement,reason}]}；不自动应用。'
MESSAGES[TASK_INSTRUCTIONS] = ('For each annotation, return replacement text for the complete selection and a short reason. '
    'Edit a multi-paragraph selection as a whole; separate replacement paragraphs with newlines and merge or redivide them when requested. '
    'Keep id and quote unchanged. Return only {project_id, results:[{id,quote,replacement,reason}]}; do not apply changes automatically.')

PROTECTION_LABELS = {
    'formula': ('公式', 'Equation'), 'footnote': ('脚注', 'Footnote'),
    'endnote': ('尾注', 'Endnote'), 'field': ('域', 'Field'),
    'comment': ('批注', 'Comment'), 'revision': ('已有修订', 'Existing tracked change'),
    'references': ('参考文献', 'References'), 'object': ('图形或对象', 'Drawing or object'),
    'citation': ('引用标记', 'Citation'), 'bookmark': ('书签', 'Bookmark'),
    'layout': ('分页或排版元素', 'Page break or layout element'), 'symbol': ('特殊符号', 'Symbol'),
    'complex': ('复杂结构', 'Complex structure'),
}

# Every template is anchored; captured external details are not globally replaced.
TEMPLATES = [
    (r'缺少字段或字段无效：(.*)', 'Missing or invalid field: {0}'),
    (r'标记 (\d+) 处表达问题', 'Flagged {0} writing issues'),
    (r'未找到 (.+?)。请先安装并在终端完成登录，或选择 API。', '{0} was not found. Install it and sign in from a terminal, or choose an API.'),
    (r'(.+?) 请求超时，请重试或缩小处理范围。', 'The {0} request timed out. Retry or use a smaller selection.'),
    (r'(.+?) 请求超时。', 'The {0} request timed out.'),
    (r'(.+?) 调用失败（退出码 (-?\d+)）：(.*)', 'The {0} request failed (exit code {1}): {2}'),
    (r'(.+?) 没有返回正文。请检查登录、模型设置及 CLI 版本。', '{0} returned no text. Check your login, model settings, and CLI version.'),
    (r'尚未设置环境变量 (.+?)。设置后重新启动文澄服务。', 'The environment variable {0} is not set. Set it and restart Wencheng.'),
    (r'API 返回 HTTP (\d+)：(.*)', 'The API returned HTTP {0}: {1}'),
    (r'PDF 校样需要包含 1 至 (\d+) 页。', 'The PDF proof must contain between 1 and {0} pages.'),
    (r'PDF 第 (\d+) 页无法读取。', 'Cannot read PDF page {0}.'),
    (r'PDF 第 (\d+) 页尺寸无效。', 'PDF page {0} has invalid dimensions.'),
    (r'PDF 第 (\d+) 页过大，请使用常规论文纸张尺寸。', 'PDF page {0} is too large. Use a standard paper size.'),
    (r'选区包含受保护内容（(.+?)），请(?:只)?选择相邻正文文字。', 'The selection contains protected content ({0}). Select adjacent body text instead.'),
]
_TEMPLATES = [(re.compile(pattern, re.DOTALL), template) for pattern, template in TEMPLATES]


def language(header: str | None = None) -> str:
    """Use supported Accept-Language preferences by quality and then order."""
    preferences = []
    for index, part in enumerate((header or '').split(',')):
        pieces = part.strip().lower().split(';')
        code = pieces[0].split('-')[0]
        if code not in ('zh', 'en'):
            continue
        quality = 1.0
        try:
            for parameter in pieces[1:]:
                if parameter.strip().startswith('q='):
                    quality = float(parameter.strip()[2:])
        except ValueError:
            continue
        if 0 < quality <= 1:
            preferences.append((quality, -index, code))
    return max(preferences)[2] if preferences else 'zh'


def protection_label(kind: str, locale: str) -> str:
    labels = PROTECTION_LABELS.get(kind)
    return labels[1 if locale == 'en' else 0] if labels else kind


def http_error(status: int, description: str, locale: str) -> str:
    messages = {
        400: ('请求无效，请检查输入。', 'Invalid request. Check the input.'),
        403: ('此操作不被允许。', 'This operation is not allowed.'),
        404: ('请求的资源不存在。', 'The requested resource was not found.'),
        405: ('此接口不支持该请求方法。', 'This endpoint does not support that request method.'),
        413: ('上传文件过大，请选择 50 MB 以内的文件。', 'The upload is too large. Choose a file no larger than 50 MB.'),
        415: ('不支持此文件或请求格式。', 'This file or request format is not supported.'),
        500: ('服务处理请求失败。', 'The service could not process the request.'),
    }
    labels = messages.get(status)
    return labels[1 if locale == 'en' else 0] if labels else message(description, locale)


def message(source: str, locale: str) -> str:
    if not isinstance(source, str):
        return source
    if locale != 'en':
        return ENGLISH_RULE_INSTRUCTIONS.get(source, source)
    if source in MESSAGES:
        return MESSAGES[source]
    if source.startswith('操作失败：'):
        return 'Operation failed: ' + message(source[len('操作失败：'):], locale)
    for pattern, template in _TEMPLATES:
        match = pattern.fullmatch(source)
        if match:
            values = [message(value, locale) for value in match.groups()]
            if source.startswith('选区包含受保护内容'):
                values[0] = protection_label(values[0], locale)
            return template.format(*values)
    return source


def mark_system_fields(item: dict, *fields: str) -> None:
    """Keep the exact system source alongside its field for safe display lookup."""
    metadata = item.setdefault('_system_fields', {})
    for field in fields:
        metadata[field] = item[field]


def mark_external_field(item: dict, field: str) -> None:
    # An explicit null prevents legacy fallback from treating a model reason as
    # a rule reason, even when the two happen to contain exactly the same words.
    item.setdefault('_system_fields', {})[field] = None


def _annotation(item: dict, locale: str) -> None:
    from .rules import RULES
    metadata = item.pop('_system_fields', {})
    legacy_rule = next((rule for rule in RULES if rule['id'] == item.get('rule_id')), {})
    if item.get('rule_id') == 'repeated-sentence':
        legacy_rule = dict(category='重复表达', reason='前文已有相同句子；检查是否为必要复现。',
            instruction='结合段落用途检查重复；若没有新增信息则删除或合并，保留必要的定义、引文和结果复述。')
    for field in ('category', 'instruction', 'reason'):
        source = metadata.get(field)
        if field not in metadata:
            # Only pending legacy rule reasons have an unambiguous system origin.
            if field != 'reason' or item.get('status') == 'pending':
                source = legacy_rule.get(field)
            if field == 'category' and item.get(field) == '用户标记':
                source = '用户标记'
            if field == 'reason' and item.get('status') == 'conflict':
                source = '此选区与已应用的修改重叠或原文已改变，请重新标记。'
        if source is not None and item.get(field) == source:
            item[field] = message(source, locale)


def response_copy(payload: dict, locale: str) -> dict:
    """Translate known API schemas, with no recursive sweep of arbitrary text."""
    result = deepcopy(payload)
    if not isinstance(result, dict):
        return result
    if isinstance(result.get('error'), str):
        canonical = result['error']
        result['error_translations'] = {'zh-CN': message(canonical, 'zh'), 'en': message(canonical, 'en')}
        result['error'] = message(canonical, locale)
    if 'annotations' in result and 'blocks' in result:
        for item in result['annotations']:
            _annotation(item, locale)
        for event in result.get('history', []):
            event['label'] = message(event['label'], locale)
        for item in result.get('protections', []):
            item['label'] = protection_label(item['kind'], locale)
        for block in result['blocks']:
            for span in block.get('protected', []):
                span['label'] = protection_label(span['kind'], locale)
    if result.get('schema') == 'wencheng.tasks.v1':
        result['instructions'] = message(result['instructions'], locale)
        for item in result.get('tasks', []):
            _annotation(item, locale)
    if 'providers' in result and 'config' in result:
        for provider in result['providers']:
            provider['label'] = message(provider['label'], locale)
    if 'progress' in result and 'project_id' in result and 'status' in result:
        labels = {'running': ('正在处理', 'Working'), 'done': ('已完成', 'Complete'), 'error': ('任务失败', 'Task failed')}
        label = labels.get(result['status'])
        if label:
            result['status_label'] = label[1 if locale == 'en' else 0]
        count = result['progress']
        result['progress_label'] = f'Completed {count} items' if locale == 'en' else f'已完成 {count} 项'
    return result
