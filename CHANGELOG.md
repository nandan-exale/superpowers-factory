# Changelog

All notable changes to superpowers-factory. Newest first. `scripts/release`
adds each new section.

## [0.2.0] - 2026-11-13

### Added

- Repo agent harness: `scripts/check` (license, JSON, config, frontmatter, compile, branding, tests), a Stop hook and CI.
- Project harness: `factory/bin/doctor`, the cached `factory/bin/stop-hook`, CI and `CLAUDE.md` wiring at install.
- Budgets per job, per hour and per day, with an evidence block in every factory PR.
- Hands-off running on macOS: `factory/bin/runner` with a sandboxed headless session under launchd.
- Auto setup: a SessionStart hook offers `/factory-install`, `/factory-update` and the factory handoff; installs record a manifest.
- `/factory-update` classifies upstream changes and migrates old configs.
- Learning loop: tagged review findings, `job learn`, the learner agent and `factory:learning` issues.
- Ships the agents-best-practices skill (MIT), pinned.

## [0.1.0] - 2026-11-12

### Added

- `/factory-handoff` files a Superpowers spec and plan as a `factory:planned` issue.
- `/factory-install` installs the vendored software factory into a project.
- `job planned` builds handed-off plans as written; reviewers and approver check plan conformance.
- Models and effort for every agent come from `factory/config.json`.
- Trusted PR comments become builder feedback.
