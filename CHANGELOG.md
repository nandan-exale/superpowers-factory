# Changelog

All notable changes to superpowers-factory. Newest first. `scripts/release`
adds each new section.

## [0.4.0] - 2026-11-13

### Added

- scripts/e2e refuses any sandbox that isn't safe to spend in
- scripts/e2e patches the sandbox config and tracks spend
- scripts/e2e checks scenario expectations
- six e2e scenarios and a learning seed
- scripts/e2e drives scenarios, writes results and cleans up
- scripts/eval reads agents, models, checks and baselines
- scripts/eval runs agents in throwaway repos under a spend cap
- job report summarises spend, throughput and what needs you
- job pause and resume; the queue and merges stop while paused
- job digest posts the report on a pinned digest issue daily
- factory-plan blocks accept part, tasks and depends
- the gate lists risky changes (dependencies, CI) in checks.md
- job queue holds a plan part until the part it depends on merges
- doctor checks the digest label and config
- install and uninstall the digest label; refresh known hashes
- job planned checks a part's task range and dependency and records them
- risky changes stop at merge until the issue has factory:risk-ok
- runner writes the report and posts the digest every tick
- /factory report, and runs end with the report and digest
- the job header names a part's task range
- builder, reviewer and approver work on a part's range only
- dashboard summary strip from report.json and a pause toggle
- handoff.max_tasks_per_part in config, checked by doctor
- factory-handoff splits large plans into ordered parts
- job scan and job push block secrets before they leave the machine
- the gate repeats the secret scan and fails on a hit
- the builder pushes through job push
- job watch follows base-branch CI after each factory merge
- a red base branch pauses the queue and opens a revert PR
- runner watches the base branch every tick
- factory skill watches first, respects the pause, resumes risk-ok jobs
- doctor checks the safety labels and config and warns when paused
- dashboard shows when the queue is paused
- install the revert and risk-ok labels; tests; refresh known hashes
- runner installs a systemd user timer on Linux
- runner reads the token from secret-tool or a 0600 file on Linux
- doctor checks the Linux runner: sandbox tools, token, linger, timer
- runner workflow renders the GitHub Actions runner workflow
- runner keeps job state on an orphan factory-state branch
- runner tick --ci restores and saves state around a lock-free tick
- job ensure-worktree recreates worktrees on a fresh machine
- the factory skill ensures a job's worktree before spawning
- doctor --ci checks the factory-state branch and the workflow
- factory-install offers the GitHub Actions runner

### Fixed

- scripts/e2e pins gh and pushes to the guarded sandbox repo
- the gate's own SECRET prefix no longer trips the secret scan
- dashboard strip lines up with the board, uses --line, says 1 day
- a missing or pull-request depends counts as a failed dependency
- the secret scan reads every branch commit, non-ASCII paths and header-like lines
- dashboard strip and pause use the 16px phone gutter
- factory:risk-ok approves only the commit that stopped; later changes stop again
- runner settings deny the Linux token file and systemd user units
- runner and doctor report a missing systemctl or loginctl instead of crashing
- runner saves factory-state without git filters, signing or risky config, and picks CI mode only from --ci
- runner never uses the ext transport and refuses remote rewrites and a symlinked jobs folder
- runner fetches, builds and pushes factory-state in a fresh isolated repository

### Changed

- chore: update software factory
- docs: Phase 2 plan; align spec with the factory's outputs
- test: eval fixtures for intake, reviewers, approver and learner
- docs: how to run scripts/e2e and scripts/eval
- docs: plans for phases 3, 4, 5a, 5b and 5c; build order in the roadmap
- Merge remote-tracking branch 'origin/main' into factory/003-add-e2e-scenarios-and
- Merge pull request #6 from nandan-exale/factory/003-add-e2e-scenarios-and
- test: job report; refresh known hashes
- test: pause and resume; refresh known hashes
- test: job digest; refresh known hashes
- test: plan block part keys; refresh known hashes
- test: risky paths in the gate; refresh known hashes
- test: queue waits on plan part dependencies; refresh known hashes
- test: planned parts; refresh known hashes
- test: risky merge stop and risk-ok resume; refresh known hashes
- test: runner tick writes the report; refresh known hashes
- test: factory skill report and digest wording; refresh known hashes
- test: part range wording; refresh known hashes
- test: dashboard strip and pause; refresh known hashes
- docs: what needs me, the digest; e2e report scenario
- test: secret scan, job push and the gate backstop; refresh known hashes
- test: watch states and recording; refresh known hashes
- docs: multi-part plans
- test: revert per merge method and on conflict; refresh known hashes
- docs: safety after the merge; e2e risky-change scenario
- test: the factory's scripts pass their own secret scan; refresh known hashes
- test: dashboard strip gutter, border token and day plural; refresh known hashes
- test: missing and pull-request dependencies, pending refusal; refresh known hashes
- test: secrets deleted later, non-ASCII names and header-like lines are caught; refresh known hashes
- test: dashboard strip and pause phone gutter; refresh known hashes
- test: a stale or early factory:risk-ok doesn't let new risky changes merge; refresh known hashes
- docs: factory:risk-ok covers the reviewed commit only
- test: systemd units, install, uninstall, status; refresh known hashes
- test: Linux token sources and sandbox tools; refresh known hashes
- Merge pull request #13 from nandan-exale/factory/006-split-large-plans-into
- test: doctor on Linux; refresh known hashes
- Merge remote-tracking branch 'origin/main' into factory/005-pause-the-queue-watch
- chore: refresh known hashes after merging main
- Merge remote-tracking branch 'origin/main' into factory/004-add-the-factory-report
- chore: refresh known hashes after merging main
- docs: hands-off running on Linux
- Merge remote-tracking branch 'origin/main' into factory/007-run-the-factory-on
- chore: refresh known hashes after merging main
- Merge pull request #12 from nandan-exale/factory/004-add-the-factory-report
- test: Linux tick refusals, missing systemd tools, Linux deny rules; refresh known hashes
- Merge remote-tracking branch 'origin/main' into factory/005-pause-the-queue-watch
- chore: refresh known hashes after merging main
- Merge remote-tracking branch 'origin/main' into factory/007-run-the-factory-on
- Merge pull request #14 from nandan-exale/factory/005-pause-the-queue-watch
- Merge remote-tracking branch 'origin/main' into factory/007-run-the-factory-on
- test: fake the Linux host tools and write no bytecode, so the suite passes on Linux
- Merge pull request #15 from nandan-exale/factory/007-run-the-factory-on
- test: Actions workflow rendering; refresh known hashes
- test: factory-state save, restore and push retry; refresh known hashes
- test: tick --ci; refresh known hashes
- test: ensure-worktree; refresh known hashes
- test: doctor --ci; refresh known hashes
- test: state save runs no repo-configured programs; plain tick on Actions; refresh known hashes
- test: ext transport, url rewrites and a symlinked jobs folder; refresh known hashes
- test: CI runner tests keep background git maintenance from racing tempdir cleanup
- test: no checkout config route runs during state save or restore; refresh known hashes
- Merge pull request #16 from nandan-exale/factory/008-run-the-factory-from

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
