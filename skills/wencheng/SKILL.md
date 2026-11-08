---
name: wencheng
description: Draft Chinese or English DOCX documents in conversation and open them in Wencheng for review, or revise existing documents using precisely anchored annotations while preserving structure, formulas, citations, comments, and tracked changes.
---

# 文澄 · Wencheng

Use the local document workspace to turn user annotations into reviewable edits.
Keep a formal, natural voice and make the smallest change that solves the stated problem.

## Start the workspace

Resolve `SKILL_DIR` to the directory containing this loaded `SKILL.md`, then use
its bundled launcher. Replace `<SKILL_DIR>` in examples with that absolute path.
For a document created in this conversation, follow **New writing** below;
its final `open` command starts the service and opens that document directly.
Use the following startup flow when opening the workspace before choosing a document:

First check `http://127.0.0.1:8765/api/health`. Reuse a service returning
`{"app":"wencheng","ok":true}`. If it is not running, launch the command below
as a background process. On Windows use `Start-Process -WindowStyle Hidden` or
Python `subprocess.Popen` with `creationflags=subprocess.CREATE_NO_WINDOW`;
redirect output to a local log and wait for the health endpoint before opening
the editor. If the port belongs to a different service, choose another port.

```text
python "<SKILL_DIR>/scripts/wencheng.py" start --port 8765
```

Open `http://127.0.0.1:8765`. The user can import a DOCX, create a document, select
text, and attach an instruction. The sidebar can call a configured model directly;
the workflow below uses the current conversation instead.

The launcher uses `WENCHENG_ROOT` when set, otherwise the installer's local
application binding, the source skill location, or a surrounding workspace.
It uses the application's `.venv` Python when available and dispatches to the
shared CLI; all entry points use the same projects. For first-time installation,
a moved application, or missing dependencies, read
[installation.md](references/installation.md).

## Apply annotations in this conversation

1. List projects with `python "<SKILL_DIR>/scripts/wencheng.py" projects`. Use the project the
   user named; if several match, ask which document they mean.
2. Read `python "<SKILL_DIR>/scripts/wencheng.py" tasks PROJECT_ID`. This exports the current
   document version, exact text ranges and instructions. Use those IDs and source
   text; do not recreate positions by searching for a repeated sentence.
3. Read [writing.md](references/writing.md) for bilingual editing criteria.
   Use each task's surrounding context and project style settings. Return a
   complete replacement for the selected range; an empty string means deletion.
   Keep explanations in the result's `reason`, outside document prose.
4. Write UTF-8 result JSON with the exported project and annotation IDs:

   ```json
   {"project_id":"PROJECT_ID","results":[{"id":"ANNOTATION_ID","quote":"原选区","replacement":"改稿","reason":"修改理由"}]}
   ```

   Keep `quote` exactly as exported. Do not recalculate ranges or invent IDs.
5. Run `python "<SKILL_DIR>/scripts/wencheng.py" apply PROJECT_ID RESULTS.json`. The application
   checks stale ranges and stores suggestions for review. The user applies each
   accepted suggestion as a Word revision in the sidebar. Add `--accept` only
   when the user explicitly requested applying these edits rather than review.

If the original range changed, reread the task and revise against its new text.
Do not bypass a conflict by overwriting the DOCX or by recreating the document.

## Editing boundaries

- Rewrite ordinary prose in body paragraphs and individual table cells.
- Preserve protected formulas, fields, citations, footnotes, existing revisions
  and reference entries. Work on a neighboring editable selection when needed.
- Preserve the author's claims, uncertainty, numbers, units and citation markers.
- User-specific rules and examples guide style; retain the document's language
  unless translation was requested.
- Use the application's DOCX export. Its original-package patching preserves
  parts that are outside the selected edit. A plain-text rebuild cannot replace it.

## New writing

The user can enter requirements in the editor to use its configured model.
When asked to create a document through this conversation, write it into a
Wencheng project and open its review page by default. Read
[writing.md](references/writing.md) for bilingual writing criteria.

Create the project and retain the exact `id` returned by the command:

```text
python "<SKILL_DIR>/scripts/wencheng.py" create --title "Document title"
python "<SKILL_DIR>/scripts/wencheng.py" append PROJECT_ID --text "One finished paragraph."
```

Append each completed paragraph so the open editor can refresh progressively.
Use a structured subprocess argument list for prose containing quotes or shell
characters; do not interpolate it into shell code. Maintain the requested level
of formality. Keep missing evidence explicit; do not invent citations, experiment
results or numeric support.

After the final paragraph has been saved, run:

```text
python "<SKILL_DIR>/scripts/wencheng.py" open PROJECT_ID
```

This starts or reuses the local service and opens the exact document in the
browser's review view. Use `--port PORT` if this workspace uses another port.
If the user requested live preview, open once after creating the project and
continue appending; the page refreshes as paragraphs arrive. Respect an explicit
request to leave the browser closed. If the user asked for an exported file,
also use `export PROJECT_ID OUTPUT.docx`.

Use the returned `url` in the final reply. `browser_opened` reports the browser
launcher's result; when browser inspection is available, verify the requested
title and saved text are visible. If it returns false, provide the direct link
and say the browser could not be opened automatically.

## Completion

For new writing, report the document title and its direct review link. For
revisions, report how many suggestions are ready or applied and link to the
project or exported file. Mention a conflict only if it prevents an intended
edit. Do not restate writing rules in the finished document.
