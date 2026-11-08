# 文澄：让 AI 修改 Word 时，每一处改动都可审阅

用途：通用中文项目介绍。适用于仓库、项目网站及允许 AI 辅助文案的平台。V2EX 和 HN 请使用各自的作者准备卡，由作者自行撰写。

---

文澄（Wencheng）是一款开源的中英文 Word 写作与审阅工作台。它把文档选区、修改要求、AI 建议和 Word 修订连在一起：先看清改了什么，再决定是否应用。

可以导入已有 DOCX，也可以在 Codex 或 Claude Code 对话中调用 skill，从提纲开始逐段写入。完成的段落会出现在本地浏览器工作台，能够继续阅读和标注。界面支持中文和英文切换。

一个典型流程是：

1. 导入论文或技术报告，选择正文或表格单元格内需要调整的文字。
2. 标注具体要求，例如“删掉重复交代，保留术语、数字和限制条件”。
3. 在当前对话里处理这些标记，或通过侧栏调用已配置的模型。
4. 比较原文与建议，逐项应用为 Word 修订，需要时添加正式批注。
5. 导出 DOCX，在 Word 中继续审阅。

文澄在原 DOCX 包中修改必要内容。公式、域、脚注尾注、参考文献及已有修订等结构受到保护，跨越保护范围的改写会要求调整选区。浏览器提供辅助版式预览；需要核对实际分页时，可以将 Word 导出的 PDF 上传为校样。

当前是早期候选版，采用 MIT 许可证。已在 Windows 上完成真实 Codex 中英文写作、改写和 Microsoft Word 检查；复杂 DOCX 往返另有独立测试。浏览器预览不能代替 Word 排版，现有样例也不构成所有 DOCX 无损往返的保证。Claude Code 和 OpenAI 兼容接口已有协议模拟覆盖，尚未完成同等真实账号验收。

运行包包含构建好的页面，需要 Python 3.11+，不需要 Node.js。通过 skills.sh 安装 skill 的方式另外需要 Node.js 22.20+，再由 skill 的 `setup` 下载并校验运行包、安装 Python 依赖。首次安装需要联网。模型服务由用户自行配置，调用时相关文本与指令会交给所选提供方。

仓库已提供中英文实际操作截图和 GIF 轮播，展示标注、比较建议及应用修订。GIF 是三个状态的轮播，不是连续录屏或模型速度测试。

- 仓库与安装：[github.com/yc13665193882-source/wencheng](https://github.com/yc13665193882-source/wencheng)
- 图文演示：[中英文截图与操作说明](https://github.com/yc13665193882-source/wencheng/blob/main/docs/DEMO.md)
- 运行包：[v0.1.0-rc.1](https://github.com/yc13665193882-source/wencheng/releases/tag/v0.1.0-rc.1)
- 安装验收：[环境和实际验证范围](https://github.com/yc13665193882-source/wencheng/blob/main/docs/launch/INSTALLATION-VALIDATION.md)
- 验收范围：[VALIDATION.md](https://github.com/yc13665193882-source/wencheng/blob/main/docs/VALIDATION.md)

欢迎尝试一份可以公开的样例，反馈安装是否顺利、标注是否准确，以及导出后遇到的具体问题。
