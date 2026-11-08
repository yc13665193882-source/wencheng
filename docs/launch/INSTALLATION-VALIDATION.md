# skills.sh installation validation

Validated on 2026-11-08 using Windows, Python 3.13.13, Node.js 24.20.0 and the official `skills` CLI 1.7.6. The application runtime remains `0.1.0-rc.1`.

## Result

**Public GitHub installation: 20 checks passed. Local-source installation: 21 checks passed.** Both runs used the actual skills CLI, a new project outside the source checkout, and a newly downloaded public runtime ZIP. Each created a new virtual environment in a path containing Chinese characters and spaces. Neither reused the developer application's Python environment. The local run has one additional check comparing the copied launcher directly with the local source file.

The public-source run installed `yc13665193882-source/wencheng` after [commit `a69baf2`](https://github.com/yc13665193882-source/wencheng/commit/a69baf22f988d85bdf9ba04e33866ca58985dbed) was published. It completed at 13:20 UTC on 2026-11-08. The installed launcher SHA256 matched that commit's source: `e01de36778f2fe3a9b1ac01cffc530c7740e1f1e7dc7825231d14c05afdf0763`. The associated [GitHub Actions run](https://github.com/yc13665193882-source/wencheng/actions/runs/42484403244) passed all five jobs.

| Area | Verified behavior |
| --- | --- |
| Discovery and installation | `skills add` discovered `wencheng` and copied the skill, launcher and references into project-scoped Codex and Claude Code directories. |
| Application bootstrap | The copied Codex skill downloaded the pinned public release, checked its SHA256, installed constrained Python dependencies, and wrote an explicit local application binding. |
| Isolation | Commands ran from an unrelated directory with `WENCHENG_ROOT`, `WENCHENG_DATA`, `PYTHONPATH` and `PYTHONHOME` removed. Neither the working directory nor installed skill had the source checkout as an ancestor. |
| Runtime and frontend | The installed skill started the downloaded application; the health response identified the expected version, and all prebuilt frontend assets matched the runtime payload. |
| Drafting | Chinese and English paragraphs written through the copied skill appeared in the HTTP document response. |
| Review | An exact annotation was exported as a task. Importing a supplied suggestion preserved the original text until acceptance. |
| Export | Acceptance produced native Word insertion and deletion elements; English text remained intact. The CLI export and HTTP download were byte-identical. |
| Second agent | The Claude Code skill copy bound to the same application and listed the same project. |

The first local-source run's GitHub release download returned HTTP 503. A second attempt from a new workspace completed successfully. The later public-source run passed on its first attempt. No alternate download source or checksum bypass was used.

This is an installation and document-workflow check. Suggestions were supplied deterministically, with **no model calls**. It does not establish a new real-Claude acceptance result or a new Word visual-layout result. See the existing [validation overview](../VALIDATION.md) for those separate checks.

The skills CLI ran with `DISABLE_TELEMETRY=1` and `DO_NOT_TRACK=1`; these test installations do not intentionally contribute to directory install counts. No global skills were installed. Local logs and detailed reports remain under ignored `test-output/`, and the temporary workspaces are retained for inspection.

## Reproduce

Requirements: Python 3.11+, Node.js 22.20+ with npm/npx, and network access to npm, GitHub release downloads and the configured Python package index.

From the source checkout:

```sh
python scripts/smoke_skills_install.py --output test-output/skills-install-smoke-local.json
```

To verify installation directly from the public repository:

```sh
python scripts/smoke_skills_install.py --source yc13665193882-source/wencheng --output test-output/skills-install-smoke-remote.json
```

The script pins `skills@1.7.6`, requests only `wencheng`, selects `codex` and `claude-code`, and uses `--copy --yes` in a fresh project directory. Each run creates a fresh application rather than modifying the user's standard installation. Add `--python PATH` to select the Python interpreter used for setup.

The recorded reports are `test-output/skills-install-smoke-local.json` and `test-output/skills-install-smoke-remote.json`. Detailed remote-run logs are in `test-output/wencheng-skills-smoke-4aw4g46s/`. Public `owner/repo` installation is verified; this is not a claim that skills.sh has already indexed or ranked the project.

Official references: [skills CLI](https://github.com/vercel-labs/skills), [skills.sh listing and telemetry FAQ](https://www.skills.sh/docs/faq).
