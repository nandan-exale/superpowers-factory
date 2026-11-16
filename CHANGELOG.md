# Changelog

All notable changes to superpowers-factory. Newest first. `scripts/release`
adds each new section.

## [0.7.3] - 2026-11-16

### Added

- accept a planned issue's spec and plan at any repo path
- hand off specs and plans from any planning tool

### Changed

- chore: update software factory
- Merge pull request #70 from nandan-exale/chore/exale-publisher

## [0.7.2] - 2026-11-15

### Changed

- Exale (https://exale.ai/) is the plugin's author in `plugin.json` and the
  marketplace owner in `marketplace.json`.

## [0.7.1] - 2026-11-15

### Fixed

- `INSTALL.md` reads the repo's merge settings with
  `gh repo view --json mergeCommitAllowed,squashMergeAllowed,rebaseMergeAllowed`
  instead of a quoted `jq` filter.
- `doctor` names the bubblewrap and socat packages instead of printing an
  `apt install` command.
- The README names the GitHub CLI without a link beside the token steps.

These clear three of the directory validator's policy holds.

## [0.7.0] - 2026-11-15

### Fixed

- shrink the listing icon to flat colours at 512px
- stop fetching the plugin from GitHub in the skills

### Changed

- refactor: move the plugin into plugin/
- Merge pull request #65 from nandan-exale/fix/listing-icon
- chore: name the factory import commit in NOTICE
- refactor: rename the plugin's bin/ to tools/
- test: check the plugin folder stays installable
- docs: split the README for the plugin folder
- Merge remote-tracking branch 'origin/main' into factory/024-move-the-plugin-into
- Merge pull request #67 from nandan-exale/factory/024-move-the-plugin-into

## [0.6.0] - 2026-11-15

### Added

- `bin/factory-handoff-check` runs the handoff checks; the handoff skill uses it.
- The learner reads one agents-best-practices reference when it drafts a rule.
- Directory listing details: icon, `homepage`, `repository`, `documentationUrl`
  and `supportUrl` in `plugin.json`; `SECURITY.md` with private vulnerability
  reporting.
- README: "What the plugin runs, writes and sends", example prompts, support,
  and why the factory is harness engineering.

### Changed

- Only one orchestrator run per clone; the runner reports a busy clone instead
  of starting another.
- `bin/job` merges the base into job branches itself, outside the builder's
  sandbox.
- Secret scanning also scans merge commits, and keeps token rules on allowed
  paths. Scanning and the report/digest code moved from `bin/job` into lib
  modules.
- The Stop hook passes its context and changed paths to `checks.sh`;
  `scripts/check` skips unit tests for docs-only runs.
- The bundled agents-best-practices skill has a shorter description.

### Fixed

- Job commands no longer deadlock on job locks.
- The session hook is `hooks/factory-session.py`, so its command line and file
  name agree on the interpreter.
- `bin/job` writes GitHub URLs in its regexes without a backslash.

## [0.5.2] - 2026-11-15

### Fixed

- let sandboxed claude agents push their job branch

### Changed

- chore: update software factory
- Merge pull request #49 from nandan-exale/chore/update-software-factory
- test: cover sandbox write paths and gh TLS for claude agents
- Merge pull request #50 from nandan-exale/fix/claude-sandbox-writes

## [0.5.1] - 2026-11-15

### Fixed

- pass --allowedTools to claude agents

### Changed

- chore: update software factory
- Merge pull request #39 from nandan-exale/chore/factory-update
- test: require --allowedTools for every claude agent role
- test: keep the missing-bwrap test off the real PATH
- Merge pull request #48 from nandan-exale/fix/claude-allowed-tools

## [0.5.0] - 2026-11-14

### Added

- runtime adapters, starting with claude -p
- agent prompts move to factory/agents with an access level
- install, update and checks follow the agents to factory/agents
- job records agent runs and costs them from run files
- gate hook reads the job from FACTORY_JOB
- orchestrator helpers for agents, scripts and prompts
- read-only check for agents that may only write their own file
- the factory pipeline as code
- orchestrate runs the pipeline with agents as child processes
- /factory run starts factory/bin/orchestrate
- runner ticks factory/bin/orchestrate
- e2e drives factory/bin/orchestrate
- external-binaries check requires a which guard for non-baseline tools
- config names a runtime and routes by model tier
- job agent resolves a role's tier to the runtime's model
- doctor checks tiers and the runtime's models
- checks and /factory-update know tiers; old configs migrate
- run caps and n/a cost for runtimes that report no cost
- runtimes without a stop hook get one checks nudge before the gate
- adapters name their binary and may rewrite the prompt file
- Codex CLI runtime adapter
- OpenCode runtime adapter; a resumed builder on it always gets the resuming prompt
- Copilot CLI runtime adapter
- Cursor CLI runtime adapter
- runner passes each runtime its own credential and installs its CLI
- builder and install wording for any agent
- plugin skills find the plugin and install for any runtime
- doctor checks the configured runtime's CLI, hooks and budgets
- scripts/e2e and scripts/eval run on any runtime
- run notify.command when a job waits on a human
- Sonnet builders below high risk, Opus intake
- a part job's plan.md holds only its own tasks

### Fixed

- a resumed builder is told about feedback newer than build.md
- scripts the orchestrator runs never read its stdin
- orchestrate refuses without its CLI and gives credentials only to agents
- runner guards security and launchctl with shutil.which
- scripts/eval gives each agent its tier's Claude model
- prefix learning folders with tag- so no tag names a secrets/ folder
- drop the runner's unused STRIPPED_ENV and TOKEN_FILE
- builders run focused tests, not the full suite
- factory agents ignore user-level settings
- reviewers raise every blocking finding in one round
- builder checks its own diff before READY
- wait out usage limits instead of escalating jobs

### Changed

- docs: phase 6 portable runtime design and 6a plan
- test: recorded claude -p output for the runtime adapter
- chore: update software factory
- test: claude adapter builds argv and parses recorded output
- test: run files, sessions and wider escalate
- test: gate hook job from the environment
- test: orchestrator helpers
- test: read-only check
- test: pipeline steps, retries, budgets and learning
- test: orchestrator loop, retries, read-only rule and stop
- test: parts wording reads the agents from factory/agents
- test: the factory skill hands the run to the script
- test: resumed build names the user's feedback
- test: job calls without input get no stdin
- test: runner starts orchestrate with the token in its environment
- docs: the orchestrator script, agents folder and run files
- test: orchestrate keeps the token from job children and needs claude on PATH
- Merge pull request #18 from nandan-exale/factory/009-run-the-factory-from
- Merge pull request #20 from nandan-exale/factory/010-factory-learning-add-an
- docs: phase 6b plan for the other agent CLIs
- test: recorded codex, opencode and cursor output for the runtime adapters
- test: tier resolution, effort fallback and legacy settings
- test: run caps, token pricing and n/a cost
- test: gate --check and the builder nudge
- test: learning folder names carry the tag- prefix
- Merge pull request #25 from nandan-exale/factory/011-run-the-factory-under
- test: a contract every runtime adapter passes against recorded output
- test: codex adapter against recorded output
- test: opencode adapter against recorded output
- test: copilot adapter against the recorded event shape
- test: cursor adapter against recorded output
- Merge pull request #26 from nandan-exale/factory/012-run-the-factory-under
- test: runner credentials and workflow per runtime; install copies every adapter
- test: doctor runtime checks
- docs: using the factory with another agent
- test: no assertion on the removed TOKEN_FILE
- Merge pull request #27 from nandan-exale/factory/013-run-the-factory-under
- docs: install into other agents with npx plugins add
- Merge pull request #28 from nandan-exale/docs/npx-plugins-install
- test: build each project fixture once per process and copy it
- perf: scripts/check runs test modules in parallel
- Merge pull request #29 from nandan-exale/perf/test-suite
- Merge pull request #30 from nandan-exale/fix/agent-permissions
- Merge pull request #31 from nandan-exale/fix/reviewer-rounds
- Merge pull request #32 from nandan-exale/fix/builder-self-check
- docs: design and plan for notifying when a job waits on a human
- docs: notify.command in the README
- Merge pull request #33 from nandan-exale/feat/notify-waiting
- Merge pull request #34 from nandan-exale/fix/usage-limits
- docs: routing by tier, and the builder defaults
- Merge pull request #35 from nandan-exale/feat/cheaper-routing
- chore: approver escalates install changes by behaviour, not every vendored edit
- Merge pull request #36 from nandan-exale/chore/approver-rule
- Merge pull request #37 from nandan-exale/feat/trim-part-plans
- chore: notify by macOS notification when a factory job waits
- Merge pull request #38 from nandan-exale/chore/repo-notify

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
