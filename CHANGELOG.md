# Changelog

All notable changes to superpowers-factory. Newest first. `scripts/release`
adds each new section.

## [0.3.0] - 2026-11-13

### Added

- known-hash list of every vendored file version
- factory-uninstall-settings removes only the factory Stop hook
- /factory-uninstall skill
- scripts/release bumps, logs, checks, commits and tags a release
- job costs and the evidence block show cost by model
- factory-handoff warns about skipped steps and approver escalations

### Fixed

- factory-update migrates old configs and settles config/settings
- evidence, merge labels and intake prompt from the first real run
- merge never blocks on labels; closes check is repo-specific
- factory-update counts every pending file and reports replaced models
- factory-update treats unedited old copies as safe without a manifest
- retry idempotent git and gh network calls in job
- fast-forward the main checkout after a factory merge
- treat glued -f, -F and -X gh api flags as writes
- factory-uninstall deletes only FILES keys and keeps factory/jobs
- planned jobs record their spec and plan paths
- gate protects a planned job's spec and plan
- builder keeps planned spec and plan fixed; skill wording for resume and base

### Changed

- docs: add README banner
- test: pending count covers a settings row with a stale core
- docs: remove references to external repositories
- docs: rewrite README for plugin users
- chore: rename the marketplace to superpowers-factory
- docs: phase 1 hardening design
- docs: phase 1 hardening plan
- docs: designs for phases 2-5 and the roadmap
- chore: install software factory
- test: network retries in job; refresh known hashes
- test: main checkout sync after merge; refresh known hashes
- docs: add CHANGELOG for 0.1.0 and 0.2.0
- docs: known hashes and releases in AGENTS.md; settle spec details
- test: glued gh api write flags run once; refresh known hashes
- Merge pull request #2 from nandan-exale/factory/001-harden-updates-merges-and
- docs: Phase 1 done in the roadmap
- docs: design and plan for factory fixes from the first self-build
- test: planned jobs record plan paths; refresh known hashes
- test: gate protects plan paths; refresh known hashes
- test: cost by model; refresh known hashes
- test: builder and skill wording; refresh known hashes
- test: queue failure test no longer waits out network retries
- Merge pull request #4 from nandan-exale/factory/002-fix-factory-issues-from

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
