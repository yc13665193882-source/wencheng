# Show HN author brief

Checked on 2026-11-08. This is background material, not a ready-to-post submission or first comment.

HN's [general guidelines](https://news.ycombinator.com/newsguidelines.html) say “Please don't put generated text in HN posts” and “Don't post generated text or AI-edited text.” Write the title, introduction, and replies yourself from your own experience. Do not paste the general English announcement or ask an AI to polish your HN submission.

## Submission fields

| Field | Preparation |
| --- | --- |
| Title | Must begin with `Show HN`. Choose concise factual wording yourself. Useful concepts: Wencheng, DOCX, reviewing AI edits, Word tracked changes. |
| URL | `https://github.com/yc13665193882-source/wencheng` — the actual project with demo and installation instructions. |
| First comment | Explain your own reason for building it, what you personally tried, the implementation choices you find interesting, and one specific area where feedback would help. |

## Facts available for the author's explanation

- Local browser workspace plus an agent skill, with Chinese and English UI and document workflows.
- Existing DOCX import and progressive drafting from an outline.
- Exact selections in body prose and table cells, attached instructions, suggestion comparison, and individual application as native Word revisions.
- Changes target the original OOXML package. Protected structures are excluded from direct rewriting; this is not a general lossless-formatting claim.
- The browser's layout view is approximate. A user-exported Word PDF can serve as a version-linked proof.
- Runtime ZIP includes the frontend. Python 3.11+ and initial network access for dependencies are needed; Node.js is not a runtime requirement.
- Installing the skill through skills.sh additionally needs Node.js 22.20+. The skill's `setup` command downloads and verifies the pinned runtime, then installs its Python dependencies. Link to the verified instructions rather than presenting this as a single-command installation.
- Actual Chinese and English UI screenshots and GIF slideshows are available. They show three review states, not continuous recording, progressive drafting, or a model-speed benchmark.
- Users provide their own model access. Relevant text goes to the chosen model provider when a model is called.
- Real Codex workflows and Microsoft Word inspection were performed on Windows. Claude and compatible API adapters currently have mock protocol coverage; they have not passed equivalent real-account acceptance.
- MIT license, early `0.1.0-rc.1` release, public synthetic fixtures and tests.

These facts can be checked against the [English README](https://github.com/yc13665193882-source/wencheng/blob/main/README.en.md), [release](https://github.com/yc13665193882-source/wencheng/releases/tag/v0.1.0-rc.1), and [validation record](https://github.com/yc13665193882-source/wencheng/blob/main/docs/VALIDATION.md). Do not claim that every platform or every Word feature has been tested.

For the trial path, use the [installation section](https://github.com/yc13665193882-source/wencheng/blob/main/README.en.md#install-through-skillssh), [installation report](https://github.com/yc13665193882-source/wencheng/blob/main/docs/launch/INSTALLATION-VALIDATION.md), and [demo walkthrough](https://github.com/yc13665193882-source/wencheng/blob/main/docs/DEMO.md). Check that these links are public after the update is pushed. A local-source test alone does not establish that the public `owner/repo` command has passed.

## Author's own first-comment outline

1. Describe a specific document-editing problem you experienced.
2. Explain the working interaction using an example you personally tried.
3. Describe why you chose DOCX package patching and reviewable edits.
4. Give the shortest verified route to trying it, and state the actual prerequisites.
5. Explain the current limitation that matters most to that example.
6. Identify a concrete question you would like to discuss with users.

Keep the product facts brief enough to leave room for the author's own experience. This outline does not supply an invented origin story or personal claim.

## Posting readiness

[Show HN guidelines](https://news.ycombinator.com/showhn.html) accept things users can run on their computers, including early work. The author should have worked on the project and be available to discuss it. A working project with a low-friction trial is appropriate; a signup or landing page alone is not.

Post manually from the author's account. Do not solicit votes or comments, arrange a coordinated boost, delete and repost to seek visibility, or automate replies. Link readers to the project and answer the technical questions they actually ask.
