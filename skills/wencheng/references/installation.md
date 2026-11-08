# Install or relocate Wencheng

The skill launches a local Python application with a prebuilt browser editor.
Python 3.11+ is required. Use `python3` in the commands below if that is the
Python 3.11+ executable on the user's machine.

## Install through skills.sh

From the user's project directory, install the skill for the agent in use:

```text
npx skills add yc13665193882-source/wencheng --skill wencheng -a codex
```

For Claude Code, replace `codex` with `claude-code`. The skills CLI currently
requires Node.js 22.20+; it installs skill files, not the Python application.
Use the actual installed skill path reported by the CLI as `<SKILL_DIR>`.
See the [skills CLI installation reference](https://github.com/vercel-labs/skills).

Set up the application explicitly, then check the launcher:

```text
python "<SKILL_DIR>/scripts/wencheng.py" setup
python "<SKILL_DIR>/scripts/wencheng.py" projects
```

`setup` downloads the fixed `v0.1.0-rc.1` runtime ZIP from
[Wencheng Releases](https://github.com/yc13665193882-source/wencheng/releases/tag/v0.1.0-rc.1),
checks its SHA256 against the value pinned in the launcher, extracts it to
`~/.wencheng/app-0.1.0-rc.1`, and installs Python dependencies into that
application's `.venv`. Download and pip installation require network access.
The browser build is included; using the installed application requires no Node.js.
Normal document commands do not download or install anything.

To choose a persistent application directory, use:

```text
python "<SKILL_DIR>/scripts/wencheng.py" setup --app-dir "<APPLICATION_DIR>"
```

Choose an empty directory outside the installed skill. Repeating setup for the
same release reuses its files and retries dependency installation. Setup does
not replace another version or overwrite a nonempty unrelated directory.
After success, `wencheng-install.json` beside `SKILL.md` records the application
path. Keep this machine-specific file out of shared skill archives.

Reload skills or start a new agent conversation. For example:

> Use Wencheng to draft a short English report, save each paragraph as it is
> completed, and open the document for review.

## Use an existing application or install without Node.js

Extract the prebuilt runtime ZIP to a directory you intend to keep and run:

```text
python scripts/setup.py
python scripts/install_skill.py --target .agents/skills/wencheng
```

Run these from the application directory. `--target` is the exact destination
skill directory, not its parent; use `.claude/skills/wencheng` for Claude Code,
or the absolute skill directory in another project. This route does not use
Node.js. A source checkout instead requires the frontend to be built with
`npm ci` and `npm run build` before use.

If the skill is already installed through skills.sh, bind it to the existing
application without copying older skill files over it:

```text
python "<SKILL_DIR>/scripts/wencheng.py" setup --bind "<APPLICATION_DIR>"
```

Binding only checks the application and prebuilt frontend and records the path;
it does not install dependencies. Run the application's `scripts/setup.py` if
its Python environment is missing or moved to another operating system.

On Windows, the application's `start.cmd` opens the editor. From any platform:

```text
python "<SKILL_DIR>/scripts/wencheng.py" start --open
```

## Relocation, updates, and resolution

The launcher checks `WENCHENG_ROOT` first, then its local `wencheng-install.json`.
An invalid explicit override or stale binding is reported instead of silently
switching documents. Without a binding, it checks its source application,
the current working directory and ancestors (including a `wencheng` child),
and finally the standard runtime location. That last location must contain
the expected Wencheng release manifest and frontend.

After moving the application, use `setup --bind` with its new path. If a skills
CLI update removes the local binding, the default runtime remains discoverable;
rebind a custom application directory. `npx skills update` updates the skill,
not the application's runtime. This setup deliberately pins one tested release.

For skills copied by the application's own installer, running the following
from the application directory updates its bundled skill and keeps extra files:

```text
python scripts/install_skill.py --target <installed-skill-directory> --update
```

The launcher enters the application's `.venv` when available; otherwise its
starting Python must already have the dependencies. `WENCHENG_DATA` optionally
sets the project-data directory. Server and CLI must inherit the same setting;
the default is `.wencheng` inside the application directory.
