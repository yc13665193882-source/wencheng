# 文澄 · Wencheng

[English](README.en.md)

文澄是面向中英文 DOCX 的本地写作与审阅工作台。它把精确选区、修改指令、模型建议和 Word 批注修订连接起来，帮助作者减少重复交代、机械强调和生硬表达，同时保留原文的论点、术语、引用与不确定性。

可以让 Codex 或 Claude Code 在当前对话里调用 skill，也可以在浏览器侧栏调用已配置的模型。两条路径共用同一组标记和文档版本。文澄不提供“AI 含量”评分，也不承诺规避检测。

当前版本为早期候选版。Windows 上已完成实际浏览器、Codex CLI 和 Microsoft Word 验收；其他系统与最低 Python 版本的验证状态见[验收概览](docs/VALIDATION.md)。

## 能做什么

- **精确标记与改写**：选择正文或表格单元格内的文字，附上修改要求；支持连续跨段选区、选区边界调整、建议对比和逐项应用。
- **两种 AI 工作流**：在当前聊天里导出任务、回传建议；或在侧栏使用 Codex CLI、Claude Code CLI、OpenAI 兼容接口。
- **逐段写入新稿**：按提纲生成中英文正文，已完成段落持续出现在工作台，可继续标注和审阅。
- **Word 原生审阅**：将建议写为插入／删除修订，按需添加正式批注；保留历史快照，支持撤销和 DOCX 导出。
- **文风与写作检查**：保存文档语言、术语规则和文风样本，检查空泛强调、重复转折等候选问题。判断结果供作者审阅，不代表原句一定需要修改。
- **三种阅读视图**：可选区的审阅视图、辅助版式预览、由用户上传 Word PDF 的校样视图。界面可在中文和英文之间切换，文档内容与界面语言独立。

## 从运行包启动

从本仓库 [Releases](https://github.com/yc13665193882-source/wencheng/releases) 下载预构建运行 ZIP，解压到准备长期保留的目录。运行包包含浏览器构建，**不需要 Node.js**；需要 Python 3.11 或更新版本，首次安装依赖需要联网。

在解压目录执行：

```text
python scripts/setup.py
```

安装程序在应用目录创建 `.venv`，按随包约束安装 Python 依赖。Windows 也可双击 `setup.cmd` 执行同一安装。若系统使用 `python3` 命令，请相应替换 `python`。

Windows 双击 `start.cmd`。macOS／Linux 使用：

```sh
.venv/bin/python scripts/wencheng.py start --open
```

浏览器地址为 `http://127.0.0.1:8765`。可在启动命令中添加 `--port 其他端口`。服务仅监听本机；这是个人本地工作台，不是多用户托管服务。

GitHub 自动生成的 Source code 压缩包是源码包，不含预构建页面；请按下方开发步骤构建。

## 安装 skill

先完成应用安装，再从应用目录选择需要的目标：

```text
# Codex：当前项目
python scripts/install_skill.py --target .agents/skills/wencheng

# Claude Code：当前项目
python scripts/install_skill.py --target .claude/skills/wencheng
```

`--target` 是这个 skill 的完整目录，支持指向其他项目或你选定的用户级 skill 目录。安装器没有默认的 home 写入位置，不修改已有安装；更新由它创建的目录时需显式添加 `--update`。安装后重新加载 skill 或开启新对话。

复制后的 skill 会记录本机应用位置，可从其他工作目录调用，并优先使用应用的 `.venv`。移动应用后，从新位置对同一目标执行安装命令并添加 `--update`，或设置 `WENCHENG_ROOT`。完整路径约定见[安装说明](skills/wencheng/references/installation.md)。

对话示例：

> 使用 $wencheng，按这份提纲写一份中文测试方案，逐段保存，完成后打开审阅页面。没有证据的地方不要编造实验结果。

> 使用 $wencheng，处理我在这份文档中标记的修改要求。先生成可审阅建议，保留术语、引文和语气强度。

skill 使用当前对话完成写作；侧栏的 CLI／API 提供方则是独立调用，需要各自可用的安装、登录或 API 配置。

## 审阅一份文档

1. 导入 DOCX。文澄保存副本，原文件不被覆盖。
2. 选中待修改的准确范围，填写指令，例如“删去重复交代，保留参数和限制条件”。
3. 在侧栏生成建议，或导出任务给当前聊天处理，再导入结果。
4. 比较原文和改稿，逐项应用为 Word 修订；需要时另加正式 Word 批注。
5. 导出 DOCX，在 Word 中继续审阅。若需核对实际分页，将当前 DOCX 在 Word 中导出 PDF，再上传到“Word 校样”。

任务记录项目、版本、标记 ID、精确原文与上下文；回传的 `quote` 必须与导出原文一致。文档变化后失效的选区会被拒绝，不通过搜索相似句子猜测落点。CLI 的 `apply` 默认只导入建议；`--accept` 会把本批建议实际写成 Word 修订。

## 格式保留与能力边界

文澄修改原 DOCX 包中的必要内容，而不是从纯文本重建全文。普通正文和单个表格单元格是主要编辑范围；连续跨段修改须处于同一节、同一单元格等兼容范围内。原生公式、域、脚注尾注、参考文献条目、已有修订及其他受保护结构不能直接改写，跨越保护边界的选区会提示调整。

未变化文字尽量沿用原 run 样式，新增文字继承邻近样式。模型无法从一段纯文本建议恢复任意复杂的混合排版。书签、批注、分页符等结构也可能限制选区。参考文献与引文识别包含启发式规则，非标准格式仍需人工核对。

**浏览器版式预览不等同于 Word 排版。** 它使用 `docx-preview`，不能保证字体、自动分页、域计算及所有复杂对象与 Word 一致。缺少分页缓存或出现溢出时会标为流式参考；特殊页码显示缓存提示。字体是否安装在当前机器上也会影响显示。

Word 校样显示上传 PDF 的实际页面，并绑定上传时的 DOCX 内容；后续修改会提示校样过期。它不自动启动 Word，也不能证明上传 PDF 确实来自该 DOCX。校样只用于查看，文字修改仍在审阅视图完成。当前上传上限为 50 MB、300 页。

已验收样例不代表所有 DOCX 都能无损往返，也不代表 WPS 或 LibreOffice 已通过相同检查。详见[验收概览与复现方法](docs/VALIDATION.md)。

## 数据与模型调用

默认项目数据保存在应用目录的 `.wencheng/`：原稿、当前 DOCX、标记、历史快照和上传校样都在本机。可用 `WENCHENG_DATA` 指定其他目录；服务、skill 与 CLI 必须继承相同设置，才能访问同一批项目。

调用模型时，选区、所需上下文、指令与文风设置会交给所选提供方；新稿生成会发送写作要求和相关上下文。是否离开本机取决于提供方。API 配置保存环境变量名，不保存 API 密钥；设置该变量后需让服务进程继承它。CLI 提供方使用本机 CLI 自己的登录配置。

Codex CLI 已完成真实中英文生成和改写验收。Claude Code 与 OpenAI 兼容接口当前完成协议模拟测试，尚未用真实 Claude 账号或真实兼容端点完成同等验收。

## 从源码开发

需要 Python 3.11+、Node.js 22.12+ 和 npm。在仓库根目录执行：

```text
python scripts/setup.py
npm ci
npm run build
```

使用上面的启动方式运行。前端为 React／TypeScript，后端为 Flask；DOCX 处理使用 lxml 和 python-docx，PDF 校样使用 PDFium。

Windows 的后端测试命令：

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

macOS／Linux 的后端测试命令：

```sh
.venv/bin/python -m unittest discover -s tests -v
```

前端回归和生产构建：

```text
node --experimental-strip-types --test frontend/tests/*.test.ts
npm run build
```

公开仓库保留合成 DOCX fixtures 和自动化检查；开发期间的真实论文副本、私人项目、模型调用产物及本机截图不随仓库或运行包分发。

## 许可证

本项目采用 [MIT License](LICENSE)。第三方依赖仍适用各自的许可证；运行包附带依赖许可清单。
