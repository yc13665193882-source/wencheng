# Install or relocate Wencheng

The skill is a launcher and editing workflow; the Wencheng application must also
be present on the same machine. A copy of this skill alone is not a server.

## Set up the application

Extract the prebuilt runtime ZIP to a directory you intend to keep. From that
directory, use Python 3.11 or later:

```text
python scripts/setup.py
```

This creates the application's `.venv` and installs its Python dependencies.
The runtime ZIP already contains the browser build. A source checkout additionally
needs Node.js 22.12 or later, `npm ci`, and `npm run build` before use.

On Windows, `start.cmd` opens the workspace. On macOS or Linux:

```text
.venv/bin/python scripts/wencheng.py start --open
```

## Install into the agent's skill directory

Run from the application directory. `--target` is the exact destination directory
for this skill, not the parent directory containing all skills. Choose a path
supported by the agent in use. For a project-local installation:

```text
python scripts/install_skill.py --target .agents/skills/wencheng
python scripts/install_skill.py --target .claude/skills/wencheng
```

The first example is for Codex; the second is for Claude Code. Run only the one
needed. To use the skill in another project, point `--target` at that project's
corresponding directory. A user-wide skill directory is also accepted when the
user explicitly chooses it. The installer has no implicit home-directory target.
Reload skills or start a new agent conversation after installation.

The installer copies the skill and writes `wencheng-install.json` beside its
`SKILL.md`, recording the application location on this machine. Keep that local
configuration out of shared skill archives. An existing nonempty directory is
left untouched unless `--update` is supplied and it is marked as a Wencheng
installation. Update from the current application directory with:

```text
python scripts/install_skill.py --target <installed-skill-directory> --update
```

Updates replace bundled skill files and retain any extra files in the target.
Use a separate file for personal notes; changes to bundled files will be replaced.

## Resolve paths and Python

The launcher checks, in order:

1. `WENCHENG_ROOT`, if set. It must name the application directory, not the skill
   directory. An invalid explicit override is reported rather than ignored.
2. The application path in its local `wencheng-install.json`, when present. A stale
   binding is reported so a different workspace is not opened by accident.
3. For a skill without that binding, its source application directory, then the current working directory
   and its ancestors, including a `wencheng` child directory.

For a moved application, rerun the installer from the new location with `--update`,
or set `WENCHENG_ROOT` in the environment inherited by the agent. Do not carry an
old machine's `.venv` to a different operating system; run setup there.

The launcher uses `<application>/.venv/Scripts/python.exe` on Windows or
`<application>/.venv/bin/python` elsewhere when present. Otherwise it uses the
Python interpreter that launched it, which must have the application's
dependencies installed. No executable or model is downloaded by the skill installer.

`WENCHENG_DATA` optionally sets the project-data directory. The server, skill, and
direct CLI must inherit the same setting to see the same projects; otherwise
data defaults to `.wencheng` under the application directory.
