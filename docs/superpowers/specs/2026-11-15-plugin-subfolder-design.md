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

Out of scope: the plugin's name, the session hook's behaviour, and the
top-level `bin/` that keeps claude.ai and Cowork from installing the plugin.

## Layout

```
plugin/                          ← submitted to the directory, installed by users
  .claude-plugin/plugin.json
  .claude-plugin/icon.png
  skills/  hooks/  bin/
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

**Runtime code: nothing.** `hooks/factory-session.py` and `bin/factory_files.py`
locate the plugin with `Path(__file__).resolve().parents[1]`, and move together
with `vendor/`, `bin/` and `skills/`.

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

**The three skills' clone fallback** (`factory-install`, `factory-update`,
`factory-uninstall`). An agent that installed only the skill folders clones the
latest `v*` tag. Until a release ships the new layout, that tag has the old
one, so the fallback picks whichever exists:

```bash
PLUGIN="<skill base>/../.."
if [ ! -d "$PLUGIN/vendor/factory" ]; then
  TAG=...   # unchanged
  CLONE=$(mktemp -d)/superpowers-factory
  git clone --depth 1 --branch "$TAG" https://github.com/nandan-exale/superpowers-factory "$CLONE"
  if [ -d "$CLONE/plugin" ]; then PLUGIN="$CLONE/plugin"; else PLUGIN="$CLONE"; fi
fi
```

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
- has a top-level `CLAUDE.md`, `tests/`, `docs/` or `scripts/`;
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
3. `test: check the plugin folder stays installable`: the `plugin-folder`
   check and its tests.
4. `docs: split the README for the plugin folder`: README move and the short
   root README, `AGENTS.md` paths.

## After merge (done by a human)

- The installed factory's project adaptations name `vendor/factory/`:
  `factory/agents/intake.md`, `factory/agents/approver.md` and
  `factory/agents/reviewer-security.md`. They're protected, so a human edits
  them to `plugin/vendor/factory/`.
- Check that `npx skills add nandan-exale/superpowers-factory` still finds the
  skills under `plugin/skills/`. If it doesn't, the README command becomes
  `npx skills add nandan-exale/superpowers-factory/plugin`.
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
