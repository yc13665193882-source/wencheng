# 公开验收概览 · Validation

记录日期：2026-11-08。版本：`0.1.0-rc.1`。

本页汇总开发阶段的自动化回归与人工验收，区分真实模型调用、固定改稿和协议模拟。公开仓库保留合成 fixtures、测试与检查脚本；原始验收目录含第三方论文副本、私人项目路径及模型调用产物，不随仓库或运行包分发。因此，下述历史人工结果是维护者的验收记录，不能仅凭公开文件逐项重放全部历史过程。

## 自动化检查

本地执行环境为 Windows、Python 3.13.13、Node.js 24.20.0、npm 11.19.0。应用最低要求 Python 3.11；依赖元数据已检查兼容该版本，但本地结果不代表 Python 3.11、Linux 或 macOS 已完成实机验收。跨平台结果以仓库 Actions 的实际运行状态为准。

| 检查 | 本地结果 | 覆盖内容 |
| --- | --- | --- |
| Python 完整回归 | 130 项通过 | DOCX 结构、精确锚点、批注修订、撤销、API、校样、模型协议、CLI、本地 Host 限制、安装、打包与版本报告 |
| 前端回归 | 42 项通过 | 选区、预览适配、本地化、保护占位符、任务轮询与临时请求失败恢复 |
| TypeScript / Vite | 生产构建通过 | 类型检查与发布页面构建 |
| npm audit | 当次完整依赖及生产依赖均为 0 项漏洞 | 仅反映该次审计结果，不是持续安全保证 |
| skill 安装专项 | 11 项通过，已包含于 Python 总数 | 显式目标、跨目录调用、路径迁移、拒绝覆盖其他 skill、参数保真、虚拟环境委派 |
| skill 规范检查 | 通过 | `SKILL.md` 的名称、描述与 frontmatter 合法性 |

安装测试仅使用测试目录，没有替用户安装或改写 home 中的 skill。虚拟环境测试涵盖 POSIX 常见的“venv 与系统 Python 指向同一二进制”路径关系；该关系在 Windows 测试中模拟，不等于完成 Linux 运行包验收。

## DOCX 往返与 Word 排版

| 样本 | 方法 | 结果与范围 |
| --- | --- | --- |
| 五页中英文合成论文 | 导入、4 处固定改稿、正式批注、逐项写入修订、导出、重导入、撤销；独立比较 ZIP 与 OOXML；Word 导出 PDF 逐页检查 | 34 项结构与流程检查通过。纵向／横向分节、公式、脚注尾注、合并表格、域与交叉引用、已有批注修订及参考文献得到覆盖。Word 源稿／改稿均为 5 页，未观察到新增裁切或分页变化；公式脚注页与参考文献尾注页像素相同。 |
| 中文 42 页、英文 38 页的真实长文档 | 各 3 处固定改稿，批注、修订、撤销、导出、重导入，源稿／改稿 Word PDF 对照 | 两份各 36 项结构与流程检查通过，页数及分节保持。未观察到新增截断、重叠或跨页影响。中文覆盖多节、公式、图表、域；两份均未包含实际脚注尾注正文或已有批注修订，不能据此宣称覆盖这些对象。 |
| Word PDF 校样 | 上传上述两份 Word PDF，逐页与独立 PDF 渲染对照；修改与撤销检查版本绑定 | 80 个校样页面与对应 PDF 独立渲染的 RGB 像素相同。正文变化后提示旧校样，撤销到相同 DOCX 内容后恢复匹配。 |

上述固定改稿用于验证文档处理，不包含真实模型文风质量评价。真实长文档中记录过极小的参考文献水平字位差异，未影响换行或分页；不声称非目标页面的每个像素在所有文件中绝对不动。

浏览器预览不是 Word 排版引擎。已修复或明确提示的差异包括缺少分页缓存、特殊页码缓存、删除修订占位、复杂公式漏显、横向分节与预览异步覆盖。真实分页判断使用 Word PDF；浏览器内容块数量不能替代 Word 页数。WPS、LibreOffice 及任意 DOCX 特性组合未在本轮完成等价验收。

## 真实 Codex 中英文流程

2026-11-08 使用已登录的 Codex CLI，分别完成中文与英文的“提纲 → 6 次逐段生成 → 精确选区改写 → 正式批注 → 应用为 Word 修订 → 导出”。使用 CLI 默认模型选择，未持久化底层模型名称或完整用量，因此不报告具体模型与计费。内容是明确标注为合成方案的环境监测节点测试稿，没有实际实验结果。

- 在浏览器看到正文逐段出现。英文生成途中添加的标记，在后续追加段落后仍保留。
- 两份导出稿各通过 46 项独立结构检查：接受新增修订得到准确建议文本，拒绝新增修订恢复原文，未选段落及无关部件保持。
- 两份均由 Microsoft Word 2021 打开，未出现修复提示，批注与修订正常显示。以“无标记”显示导出 PDF，没有接受全部修订或重新保存 DOCX。
- 两份 PDF 均为 2 页；去除空白后，与有效 DOCX 正文分别为 1,138 字符和 3,800 字符逐字一致。检查全部 4 页，未发现截字、缺字、重叠或页外溢出。

本轮保留以下观察和未通过项：

1. 中文 PDF 的末页仅有最后两行，标题末行也较短。这是排版紧凑度观察，没有发现丢文，没有为凑页更改字体或边距。
2. 英文浏览器点击导出后，未取得可确认的下载落盘文件；同一 DOCX 已通过 CLI 导出、HTTP 响应及项目字节一致性检查，并在 Word 打开。本轮不据此宣称英文浏览器下载交付通过。
3. 改写要求“约缩短 20%”，独立测量为中文 10.81%、英文 14.56%。模型理由中的比例自述不准确，严格长度目标未通过；精确锚点、事实保留及修订写入通过。
4. 本轮真实调用文档为普通正文，不包含复杂公式、脚注或表格。它不能替代前述复杂结构验收。

Claude Code CLI 与 OpenAI 兼容接口目前完成协议模拟测试，包括流式响应处理；尚无同等的真实 Claude 账号或真实兼容端点调用验收。网络故障恢复使用模拟请求回归，不宣称已在真实模型调用中注入网络故障。

## 中英文界面

浏览器检查覆盖界面语言切换和重载记忆、页面 `lang` 与标题、六个侧栏及写作／AI 设置弹窗、错误与表单校验、日期和计数。未保存的中英混合正文、用户规则和文风设置在往返切换后保留；文档语言与界面语言独立。

使用英文界面处理真实英文文档，完成短语标注、任务导出、固定建议回导、Word 批注、应用修订、历史与导出；独立 OOXML 检查 35 项通过。该次任务回导是固定结果，没有冒充外部真实 AI 调用。

合成复杂文档中的公式、脚注等生成占位符显示英文后，仍保留原始偏移协议；实际鼠标选择其后 5 个中文字符并保存成功。保护占位符的可访问标签以及移动端导出按钮名称已复核。1280×800 和 375×812 视口未观察到页面水平溢出，移动菜单正常；宽版式文档自身仍可在其预览容器内水平滚动。

## 在公开源码中复现

先按 [README](../README.md) 安装应用与开发依赖。以下 Python 命令在已激活应用 `.venv` 的终端运行；也可使用 README 中对应系统的 `.venv` Python 完整路径。

```text
python -m unittest discover -s tests -v
node --experimental-strip-types --test frontend/tests/*.test.ts
npm run build
python scripts/acceptance_roundtrip.py --output test-output/public-roundtrip
```

最后一条使用公开的 `tests/fixtures/complex-academic.docx` 及其 inventory，输出独立审计、源稿与导出稿到测试目录。它验证固定改稿的处理链，不调用模型，不自动生成 Word PDF。自动化结构审计也包含损坏公式、域缓存、批注或参考文献的反例，验证检查能够检出失败。

手工复验时，用本机 Word 分别打开源稿与导出稿，在相同修订显示方式下导出 PDF，比较页数、纸张、分页、修改位置及未改区域；记录 Word 版本和字体环境。模型验收需另行配置提供方，使用同一份事实与指令，独立核对修改范围和数字，不采用模型自述作为统计结果。

## English summary

This is a public summary of local acceptance, not a redistribution of the original evidence archive. The repository includes synthetic fixtures and executable tests; third-party papers, private paths, project data, and model-run artifacts remain excluded.

Windows validation covers 130 Python tests, 42 frontend tests, the production build, a complex synthetic DOCX round trip, two long Chinese/English documents inspected in Word, and genuine Codex generation and rewriting in both languages. The minimum Python version and non-Windows execution still require the corresponding successful CI or manual run; package metadata compatibility is not a substitute.

The latest English browser download was not confirmed, although CLI/HTTP export bytes and Word opening were verified. The model did not meet the requested approximate 20% shortening target. Browser layout remains approximate; real pagination was checked with Word-exported PDFs. Claude and compatible API coverage is currently mocked. The commands above reproduce public automated coverage, not every historical manual or real-model acceptance run.
