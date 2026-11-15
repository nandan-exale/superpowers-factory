# Move the plugin into `plugin/`

## Why

Anthropic's plugin directory submits and installs the folder that holds
`.claude-plugin/plugin.json`. Today that is the repo root, so the listing would
ship `tests/` (185 files), `docs/`, `scripts/`, the installed `factory/` copy,
`.claude/settings.json` and `CLAUDE.md`, about 350 files. The directory holds a
plugin over 512 files for a reviewer, warns on a root `CLAUDE.md`, and its
secret scan would read the fake `sk-test-` key in `tests/evals/` fixtures.
Users never need any of those files.

## Goal

The plugin folder is `plugin/` and contains only what installed users run or
read. Development files stay at the repo root. Users who already installed the
plugin get the new layout through a normal `/plugin marketplace update`, with no
spurious `/factory-update` offer.

Two changes ride along, because the directory's validation flagged them and
both touch the same paths:

- `bin/` becomes `tools/`. Claude Code puts a plugin's `bin/` on `PATH`; the
  directory will later accept `bin/` only from Verified organizations, and
  claude.ai and Cowork refuse to install a plugin that has one. Nothing
  relies on `PATH`: the skills and the hook call these scripts by path.
- The three skills stop cloning a release from GitHub when they find no
  plugin files beside them. The directory flags that as download-and-execute
  (`RUNTIME_FETCH_EXEC`): code that runs but was never reviewed.

Out of scope: the plugin's name and the session hook's behaviour.

## Layout

```
plugin/                          ← submitted to the directory, installed by users
  .claude-plugin/plugin.json
  .claude-plugin/icon.png
  skills/  hooks/  tools/          (was bin/)
  vendor/factory/  vendor/known-hashes.json
  assets/banner.svg
  README.md                      the full user README (moved from the root)
  LICENSE                        identical copy of the root LICENSE
.claude-plugin/marketplace.json  plugin source "./plugin"
README.md                        short: one paragraph, install commands, links
LICENSE  SECURITY.md  CHANGELOG.md  AGENTS.md  CLAUDE.md
tests/  scripts/  docs/  factory/  .claude/  .github/
```

- `LICENSE` and `SECURITY.md` stay at the root because GitHub detects them
  there. `plugin/LICENSE` is a copy; `scripts/check` fails if the two differ.
- `plugin/README.md` links to `SECURITY.md`, `AGENTS.md` and contributing notes
  by absolute GitHub URL, since those files aren't in the installed folder.
- The root `README.md` keeps the banner, the one-paragraph pitch, the two
  install commands, and links to `plugin/README.md`, `AGENTS.md` and
  `CHANGELOG.md`.

## What changes

**Runtime code: only the `bin/` → `tools/` rename.** `hooks/factory-session.py`
and `tools/factory_files.py` locate the plugin with
`Path(__file__).resolve().parents[1]`, and move together with `vendor/` and
`skills/`, so the move itself changes no runtime path. The rename changes
`PLUGIN / "bin"` to `PLUGIN / "tools"` in the hook, `$PLUGIN/bin` to
`$PLUGIN/tools` in the skills, and `bin/factory-state` to
`tools/factory-state` in the README.

**Hashes: nothing.** `vendor_hash()` and `vendor/known-hashes.json` are keyed by
paths relative to `vendor/factory/`. The implementer records `vendor_hash()`
before the move and compares it after; `scripts/known-hashes --check` (already
in `scripts/check`) catches any content change.

**Hash history: follow the rename.** `scripts/known-hashes` lists every
version of each vendored file from `git log -- <path>`, which stops at a
rename. It switches to `git log --follow --name-only` and reads each blob at
the path that commit had, so the regenerated `known-hashes.json` is identical
to today's and `/factory-update` still recognises unedited old installs. A
test regenerates the list and compares it with the committed file.

**Repo-side paths** gain the `plugin/` prefix:

- `scripts/check` (`JSON_FILES`, `check_license`, `FACTORY`, the version
  comparison), `scripts/known-hashes`, `scripts/release` (`PLUGIN_JSON`,
  `HASHES`), `scripts/e2e`, `scripts/eval`.
- Tests that build paths from `parents[1]` to `vendor/`, `skills/`, `bin/`,
  `hooks/` or `.claude-plugin/plugin.json`. Each such test gets
  `PLUGIN = Path(__file__).resolve().parents[1] / "plugin"`; tests that mean
  the repo root keep `REPO`.
- `tests/factory_project.py` and `tests/installed_project.py`, which copy the
  vendored factory into throwaway projects.

**The three skills find the plugin, or stop** (`factory-install`,
`factory-update`, `factory-uninstall`). Their "Find the plugin" section sets
`PLUGIN="<skill base>/../.."`. If `$PLUGIN/vendor/factory` doesn't exist, the
agent got the skill folders without the rest of the plugin; the skill stops
and tells the user to install the whole plugin with
`npx plugins add nandan-exale/superpowers-factory` (other agents) or
`/plugin install` (Claude Code). No `git clone`, no tag lookup. The README's
"Using another agent" section drops `npx skills add` for `npx plugins add`,
and "What leaves your machine" drops the release download.

**`vendor/factory/NOTICE`** says "the first commit in `git log --
vendor/factory` is the unmodified import". After the move, that log starts at
the move commit. NOTICE will name the import commit by hash and say every
later commit touching the factory's files is a modification. This is a
vendored edit: its own commit, with `scripts/known-hashes` rerun.

**`AGENTS.md`**: the Map and Invariants sections use the `plugin/` paths.

## New check: `plugin-folder`

`scripts/check` gains a `plugin-folder` check that fails when `plugin/`:

- holds more than 400 files (the directory holds a plugin at 512);
- has a file over 256 KiB that isn't a PNG, JPEG, GIF, WebP or SVG;
- has `.DS_Store`, `Thumbs.db`, `desktop.ini` or `__MACOSX`;
- has a top-level `CLAUDE.md`, `tests/`, `docs/`, `scripts/` or `bin/`;
- has a string matching `sk-[A-Za-z0-9-]{16,}`;
- has a `LICENSE` that differs from the root `LICENSE`.

Each rule gets a test in `tests/test_check.py`, in the existing style
(`self.edit(...)` then `assertFails`).

## Commits

One PR, made interactively: the factory can't do it, because a factory job may
not change the installed copy that the move leaves stale (see "After merge").

1. `refactor: move the plugin into plugin/`: `git mv` plus the path edits
   needed for `scripts/check` to pass. No content changes beyond paths.
2. `chore: name the factory import commit in NOTICE`: the NOTICE edit and the
   refreshed `plugin/vendor/known-hashes.json`.
3. `fix: stop fetching the plugin from GitHub in the skills`: the "Find the
   plugin" sections and their README lines.
4. `refactor: rename the plugin's bin/ to tools/`: the rename and every path
   to it.
5. `test: check the plugin folder stays installable`: the `plugin-folder`
   check and its tests.
6. `docs: split the README for the plugin folder`: README move and the short
   root README, `AGENTS.md` paths.

## After merge (done by a human)

- The installed factory's project adaptations name `vendor/factory/`:
  `factory/agents/intake.md`, `factory/agents/approver.md` and
  `factory/agents/reviewer-security.md`. They're protected, so a human edits
  them to `plugin/vendor/factory/`.
- Check that `npx plugins add nandan-exale/superpowers-factory` installs from
  `plugin/` (it reads the marketplace's `source`).
- Delete the portal's existing draft (saved for the repo root, before the
  icon existed) and submit again with plugin path `plugin`.
- Run `/plugin marketplace update superpowers-factory` once, and confirm the
  session hook still fires.

## Done when

- `scripts/check` passes, including `plugin-folder`.
- `claude plugin validate plugin` passes, without the `CLAUDE.md` warning.
- `claude plugin validate .` passes for the marketplace.
- `plugin/` holds fewer than 120 files.
- `vendor_hash()` is unchanged from before the move.
