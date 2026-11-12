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
- `scripts/check`: every repo rule. `scripts/check-hook`: the Stop hook.
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

- Run `scripts/check` before saying work is done. `scripts/check --fast`
  skips the unit tests. The Stop hook runs it for you when the tree has changes.
- New features: `superpowers:brainstorming` → spec in `docs/superpowers/specs`,
  `superpowers:writing-plans` → plan in `docs/superpowers/plans`, then TDD.
- Bug fixes get a regression test in `tests/`.
- Don't commit or push unless asked. Never force-push without confirmation.
