# Wencheng: review AI edits in Word with precise selections and tracked changes

Use: general English project announcement for the repository, project website, or channels that permit AI-assisted copy. For Hacker News and V2EX, use the author briefs and write your own submission.

---

Wencheng is an open-source local writing and review workspace for Chinese and English DOCX documents. It connects a selected passage, an editing instruction, a proposed rewrite, and native Word tracked changes. Authors can inspect each suggestion before applying it.

You can import an existing document or invoke the skill from a Codex or Claude Code conversation to draft from an outline. Completed paragraphs appear in the browser workspace as they are saved, where they remain available to read and annotate. The interface supports both Chinese and English.

A typical workflow:

1. Import a paper or technical report and select prose in the body or a table cell.
2. Attach a specific instruction, such as removing repeated framing while preserving terminology, numbers, and limitations.
3. Process those annotations in the current conversation or use a configured provider in the sidebar.
4. Compare the original and the suggestion, apply individual suggestions as Word revisions, and optionally add formal comments.
5. Export DOCX and continue reviewing in Word.

Wencheng patches the relevant parts of the original DOCX package. Equations, fields, footnotes, endnotes, reference entries, existing revisions, and other protected structures are kept outside direct rewriting. An edit crossing a protected boundary needs a narrower selection. The browser offers an approximate layout preview; a PDF exported from Word can be uploaded as a proof for checking actual pages.

This is an early release candidate under the MIT license. Real Codex drafting and rewriting in both languages have been exercised on Windows, with exported files inspected in Microsoft Word. Separate tests cover complex DOCX structures. These results do not establish lossless handling of every document. Claude Code and OpenAI-compatible adapters currently have protocol-level mock coverage, without equivalent real-account acceptance.

The prebuilt runtime needs Python 3.11+ and includes the browser build, so Node.js is not required to run it. Installing the skill through skills.sh additionally requires Node.js 22.20+; the skill's `setup` command then downloads and verifies the pinned runtime and installs Python dependencies. Initial installation requires network access. Model services are configured by the user, and model calls send the relevant text and instructions to the chosen provider.

The repository includes actual Chinese and English UI screenshots and GIF slideshows of annotation, suggestion comparison, and applying tracked changes. These are three-state slideshows, not continuous recordings or model-speed benchmarks.

- Repository and installation: [Wencheng](https://github.com/yc13665193882-source/wencheng)
- Demo: [Chinese and English screenshots and walkthrough](https://github.com/yc13665193882-source/wencheng/blob/main/docs/DEMO.md)
- Runtime download: [v0.1.0-rc.1](https://github.com/yc13665193882-source/wencheng/releases/tag/v0.1.0-rc.1)
- Installation validation: [tested environment and scope](https://github.com/yc13665193882-source/wencheng/blob/main/docs/launch/INSTALLATION-VALIDATION.md)
- Validation: [coverage and limitations](https://github.com/yc13665193882-source/wencheng/blob/main/docs/VALIDATION.md)

Feedback on installation, selection accuracy, and exported documents would help shape the next release. A small, shareable sample and the steps that reproduce a problem are especially useful.
