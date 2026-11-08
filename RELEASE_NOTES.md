# Wencheng v0.1.0-rc.1

文澄首个公开候选版本：在本地浏览器中审阅中文、英文 DOCX，通过精确选区提示调用 AI，逐条接受为正式 Word 修订。

## 安装

下载本 Release 的 `wencheng-0.1.0-rc.1.zip`，完整解压到可写目录。需要 Python 3.11 或更新版本以及首次安装依赖时的网络连接。

- Windows：双击 `setup.cmd` 安装依赖，再双击 `start.cmd`。
- 其他系统：运行 `python3 scripts/setup.py`，然后 `.venv/bin/python scripts/wencheng.py start --open`。
- 包内已构建前端，使用 Release ZIP 无需 Node.js；GitHub 自动生成的 Source code 压缩包需要自行构建前端。
- Codex / Claude skill 安装见 README。AI 侧栏调用需要自行安装、登录对应 CLI，或配置兼容 API。

同名 `.zip.sha256` 文件提供下载校验值，包内 `RELEASE-MANIFEST.json` 列出各文件的 SHA-256。应用与第三方依赖分别遵循 MIT 和包内保留的上游许可证。

## 首版功能

- 完整中文与英文界面，界面语言和正文语言独立设置。
- 导入已有 DOCX，或从提纲逐段生成；已完成的段落可阅读和标注。
- 正文及表格单元格内的精确选区、修改提示、原文与改稿对照、逐条接受和忽略。
- 正式 Word 批注与插入／删除修订，保留未修改的 OOXML 部件。
- 表达问题检查、自定义规则与文风样本、保护区域、版本撤销。
- 浏览器版式参考及绑定当前文档的 Word PDF 校样。
- 侧栏 Codex CLI、Claude CLI、兼容 OpenAI 的 API；也可通过 skill 使用当前聊天。

发布前修复了临时请求失败导致前端停止跟踪 AI 任务的问题，并限制本地服务仅接受可信本机 Host，拒绝外部域名请求。

## 验证与已知边界

本机已通过 130 项 Python 测试、42 项前端测试及生产构建；依赖审计当次报告 0 项漏洞。真实 Codex 中英文六段生成、选区改写、修订导出及 Word 排版检查已完成。完整覆盖范围见 [docs/VALIDATION.md](https://github.com/yc13665193882-source/wencheng/blob/v0.1.0-rc.1/docs/VALIDATION.md)。

- 本轮 Windows 验证不代表其他操作系统或所有 Word/WPS 版本均已验证；跨平台 CI 结果以仓库 Actions 为准。
- HTML 预览与 Word 可能有字体、换行和分页差异；需要实际分页时使用 Word 导出的 PDF 校样。
- 公式、脚注、引用、域和已有修订等区域保留且保护，不自动改写。
- Claude CLI 和兼容 API 已通过模拟接口测试，尚未完成真实账号调用验收。
- 最近一轮英文浏览器下载落盘尚未确认；同一 DOCX 的 CLI 导出、HTTP 字节核对及 Word 打开已通过。
- 模型可能未精确达到提示词中的压缩比例。当前检查是表达候选定位，不是 AI 生成概率检测。

## English

Wencheng's first public release candidate provides a local bilingual DOCX review workspace: precise annotations, AI suggestions, individual acceptance as Word tracked changes, formal comments, history, and progressive drafting from an outline.

Download `wencheng-0.1.0-rc.1.zip`, extract it, and install Python 3.11+. On Windows, run `setup.cmd` followed by `start.cmd`. The ZIP includes the built frontend and does not require Node.js. See [README.en.md](https://github.com/yc13665193882-source/wencheng/blob/v0.1.0-rc.1/README.en.md) for source installation, skill setup, AI configuration, and limitations.

Validated locally: 130 Python tests, 42 frontend tests, production build, and genuine Chinese/English Codex generation and rewriting followed by Microsoft Word inspection. HTML preview is a layout reference; uploaded Word PDFs provide actual pagination. Real-account Claude/API testing and the latest English browser-download delivery remain unverified. The project is released under the MIT license, with upstream notices included.
