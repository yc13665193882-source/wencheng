# 文澄 60–90 秒演示分镜

**当前已有素材：** [图文演示](../DEMO.md)包含中英文各三张真实界面截图；首页使用[中文 GIF](../media/wencheng-demo-zh.gif)和[英文 GIF](../media/wencheng-demo-en.gif)串联三个审阅状态。建议由当前对话生成并导入，在浏览器应用。这些 GIF 不是连续录屏，轮播时长不代表模型速度。

下文是尚未完成的 60–90 秒连续录屏计划。它新增了逐段生成、复杂合成论文和 Word 原生窗口等镜头，不能将这些镜头描述为现有 GIF 已经展示的内容。

目标：让第一次看到文澄的人理解“逐段写作 → 精确标注 → 审阅建议 → Word 修订交付”。做一份中文和一份英文字幕，复用同样的操作顺序。

## 素材与录制方式

- 只使用仓库公开的合成 DOCX 样例或新建的合成测试方案。可选 `tests/fixtures/academic-bilingual.docx`、`tests/fixtures/complex-academic.docx`；文中的数字和参考文献不是实际研究结果。
- 使用专门的演示项目，不展示个人项目列表。开始前收起账号头像、终端历史、私人目录、API 配置和通知。
- 逐段生成和复杂格式保留是两个场景。切换时在画面中写清“导入另一份合成样例”，避免让观众以为自动生成的普通正文已经包含复杂论文结构。
- 真实模型等待可以加速，但画面标明加速倍数。固定建议回导须标为“示例建议 / Example suggestion”，不能伪装成现场模型响应。
- 使用屏幕上真实存在的控件和文字。演示结束导出的文件必须与该项目、该版本一致。

## 90 秒版本

| 时间 | 画面与操作 | 中文字幕 | English caption |
| --- | --- | --- | --- |
| 0–7 秒 | 打开工作台，显示一个简短提纲与已完成的首段 | 从提纲开始，完成一段就保存一段 | Start from an outline. Save each completed paragraph. |
| 7–18 秒 | 真实逐段写入，已完成段落保持可见；如加速则显示倍率 | 写作还在继续，已有内容可以阅读和标注 | Read and annotate completed text while drafting continues. |
| 18–25 秒 | 切换到导入的复杂合成 DOCX，展示正文与公式或脚注 | 导入另一份合成论文样例 | Import a separate synthetic paper sample. |
| 25–39 秒 | 在 Review 中选中一处重复表达，输入具体修改要求，保存标记 | 选中准确范围，写下修改要求 | Select the exact passage and attach an instruction. |
| 39–54 秒 | 显示实际建议，查看原文与改稿；若使用固定结果明确标注 | 先比较原文与改稿，再决定是否应用 | Compare the original and suggestion before applying it. |
| 54–64 秒 | 应用一条建议为修订，按需添加 Word 批注 | 建议写成 Word 修订，仍可继续审阅 | Apply as a Word revision for further review. |
| 64–79 秒 | 导出并在 Word 打开，显示插入／删除、批注及相邻公式/脚注 | 导出 DOCX，在 Word 中查看改动与原有结构 | Export DOCX and inspect changes and retained structures in Word. |
| 79–90 秒 | 返回项目首页或干净结束卡，显示仓库与安装要求 | 中英文界面 · 本地工作台 · Python 3.11+ | Chinese and English UI · Local workspace · Python 3.11+ |

若需要 60 秒版本，省略新稿生成的前两镜，从“导入合成样例”开始。不要用极快切镜把实际不可见的步骤暗示为已经展示。

## 可用的选区与指令

中文指令：`删去重复交代和空泛强调，保留术语、数字、引用以及限制条件。只修改选中的文字。`

English instruction: `Remove repetitive framing and empty emphasis. Preserve terminology, numbers, citations, and limitations. Change only the selected text.`

应在样例中选择普通正文，不跨越公式、书签或脚注等保护边界。无需为了演示强行修改复杂对象。

## 画面核对

- [ ] 中文和英文字幕与实际操作一致，字号可在 GitHub 页面读清。
- [ ] 选区、指令、建议、导出文件属于同一次演示流程。
- [ ] Word 中清楚显示插入／删除修订，未误用“接受所有修订”抹去审阅信息。
- [ ] 如展示格式保留，能看到对应样例中的公式、脚注或引用；不以单个样例宣称所有格式无损。
- [ ] 未将浏览器近似预览或旧 Word 校样呈现为最终 Word 分页。
- [ ] 任何加速、剪辑和固定建议都有说明；没有不存在的实时响应或虚构耗时。
- [ ] 仓库链接可读，结束卡不包含失效下载地址或尚未验证的安装命令。

## 配套静态截图

首页现有两种语言各三张实际截图：①选区与指令；②原文／改稿对照；③文澄中应用为修订后的审阅记录。它们均来自文澄浏览器界面，未包含 Word 原生窗口。后续录屏可另补 Word 窗口镜头。截图是录屏以外的独立交付，不替代完整安装流程验证。
