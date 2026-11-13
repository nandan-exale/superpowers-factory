# Agent instructions for superpowers-factory

A Claude Code plugin: Superpowers designs a feature, and a vendored software
factory builds each approved plan as one PR. See `README.md` for what users do.

## Map

- `skills/factory-install`, `skills/factory-handoff`: this plugin's skills.
- `vendor/factory/`: the vendored factory, with edits. `factory/bin/job` is the
  job state machine; `factory/config.json` holds models, efforts and routing;
  `.claude/skills/factory` is the orchestrator; `.claude/agents/` the agents.
- `tests/`: stdlib `unittest`. `tests/factory_project.py` builds a throwaway
  project with a bare origin.
- `scripts/check`: every repo rule. The Stop hook is the installed factory's
  `factory/bin/stop-hook`, which runs `factory/checks.sh` (= `scripts/check`).
- `factory/`, `.claude/agents/`, `.claude/skills/factory/`: the factory
  **installed** in this repo to build it (see "Software factory" below). Not the
  source: change `vendor/factory/` instead. The installed copy changes only
  through `/factory-update`, by a human.
- `scripts/known-hashes`: writes `vendor/known-hashes.json`, every hash each
  vendored file has had, so `/factory-update` recognises unedited old copies.
  `--check` (run by `scripts/check`) fails when a current version is missing.
- `scripts/release`: bumps the version, writes `CHANGELOG.md`, commits and tags.
- `bin/factory-uninstall-settings`: removes only the factory's Stop hook from a
  project's `.claude/settings.json`; `skills/factory-uninstall/` is the
  `/factory-uninstall` skill that uses it.
- `docs/superpowers/specs`, `docs/superpowers/plans`: approved designs and plans.

## Invariants

- `factory/bin/job` is the only writer of `job.json`.
- Factory code and scripts use the Python standard library only. Ask before
  adding any dependency.
- No agent or skill frontmatter sets `model`. Models and efforts come from
  `factory/config.json` (`model_aliases`, `effort_levels`, `agents`,
  `routing`, `surface_reviewers`).
- Keep `LICENSE` (GPLv3) and `vendor/factory/NOTICE`. Every commit after the
  unmodified import counts as a modification, so make vendored edits in their
  own commits.
- No upstream branding anywhere; `scripts/check` enforces it.
- Superpowers core is never modified; this plugin only uses its skills.

## Workflow

- Set up a fresh checkout: nothing to install; Python 3.10+ and git are enough.
- Run `scripts/check` before saying work is done. `scripts/check --fast`
  skips the unit tests. The Stop hook runs it for you when the tree has changes.
- New features: `superpowers:brainstorming` → spec in `docs/superpowers/specs`,
  `superpowers:writing-plans` → plan in `docs/superpowers/plans`, then TDD.
- Bug fixes get a regression test in `tests/`.
- Interactive sessions: don't commit or push unless asked. Factory jobs (in a
  `.worktrees/<job-id>` worktree) commit and push their job branch as their
  agent instructions say. Nobody force-pushes without a human's confirmation.
- Edited a vendored file? Run `scripts/known-hashes` and commit
  `vendor/known-hashes.json` with your plugin-side changes (`scripts/check`
  fails until you do).
- Releasing: `scripts/release X.Y.Z` on a clean `main`. It bumps both
  manifests, refreshes the known hashes, adds a CHANGELOG section from the
  commit subjects since the last `v*` tag, runs `scripts/check`, commits and
  tags. It never pushes; it prints the push command.

## Software factory

`/factory run` builds every open GitHub issue labeled `factory` through
intake → spec → build → gate → review → approve, one PR per issue. State is in
`factory/jobs/` (gitignored); `factory/bin/job` is its only writer. Checks:
`factory/checks.sh`. Dashboard: `cd factory && python3 -m http.server`, then
open http://localhost:8000/dashboard.html.

Each job works in its own git worktree, a full checkout of the repo at
`.worktrees/<job-id>` (gitignored). A tool run from the repo root that doesn't
read `.gitignore` sees those copies too; exclude `.worktrees/` in its config.

Issues labeled `factory:planned` were designed with Superpowers and filed
with `/factory-handoff`. They skip intake and the spec writer: the factory
copies the committed spec and plan, and the builder carries out the plan.

This repo is the factory's own source. A job that changes the factory edits
`vendor/factory/`; the installed copy in `factory/` and `.claude/` is
protected (`protected_paths`) and only `/factory-update` changes it.
