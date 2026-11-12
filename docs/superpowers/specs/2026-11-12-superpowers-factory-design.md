# superpowers-factory — Design

Date: 2026-11-12
Status: approved design, pending implementation plan

## Goal

Use Superpowers for design and a vendored software factory for
unattended execution. You brainstorm and plan interactively with Superpowers;
each approved plan becomes one GitHub issue that the factory builds, gates,
reviews, and merges (or escalates) as one PR.

Upstream factory: <<upstream repository URL>>,
pinned at commit `5fc7c983f44d623057ef65361f25cf23cab2abef`.

## Decisions

| Question | Decision |
|---|---|
| Division of labor | Superpowers designs (brainstorming → writing-plans); the factory builds. |
| Unit of work | One factory issue per plan. The builder executes all plan tasks in order on one branch → one gate/review/PR cycle. Plans should stay feature-sized. |
| Packaging | A personal Claude Code plugin, `superpowers-factory`, separate from Superpowers core. GPLv3, because it vendors modified factory files. Superpowers itself is not modified. |
| Pre-specced issues | No intake agent and no spec-writer for planned issues. The handoff skill proposes risk/surfaces and you confirm; a script writes `intake.md` and copies the committed spec and plan. |

## Architecture

```
superpowers-factory/
  .claude-plugin/plugin.json
  skills/
    factory-install/SKILL.md     install the factory into the current project
    factory-handoff/SKILL.md     committed spec + plan → one factory:planned issue
  vendor/factory/                upstream v2 files at the pinned commit, with our edits
    UPSTREAM                     upstream URL + pinned sha
    .claude/skills/factory/SKILL.md      edited
    .claude/agents/*.md                  builder, reviewer-code, approver edited; rest unchanged
    factory/bin/job                      edited: `planned` subcommand, one new transition
    factory/bin/gate, factory/bin/route  unchanged
    factory/config.json                  edited: labels.planned
    factory/checks.sh, dashboard.html    unchanged
    INSTALL.md                           upstream, referenced by factory-install
  tests/
    test_job_planned.py          stdlib unittest
  LICENSE                        GPLv3
```

### Flow

```
brainstorming   → spec committed  (docs/superpowers/specs/…)
writing-plans   → plan committed  (docs/superpowers/plans/…)
/factory-handoff (instead of choosing subagent-driven-development or executing-plans)
   → checks spec + plan are on origin/<base>
   → proposes risk + surfaces from the plan; you confirm or change them
   → gh issue create, labels: factory, factory:planned, body holds the handoff block
/factory run    (later, unattended, ideally a separate session)
   → planned path: bin/job planned → builder → gate → reviewers → approver → PR
```

## Components

### factory-install (skill)

Runs in the target project. It:

1. Refuses if Superpowers is not installed (the builder invokes Superpowers skills).
2. Copies `vendor/factory/` into the project (`.claude/skills/factory`, `.claude/agents`, `factory/`).
3. Follows the upstream `INSTALL.md` steps: fill `factory/checks.sh` with the project's real test/lint/typecheck/build commands, tailor reviewers to the stack, create labels, confirm `checks.sh` passes on the base branch.
4. Also creates the `factory:planned` label and makes sure `factory/jobs/` and `.worktrees/` are gitignored.

It does not commit or push. You review and commit the install.

### factory-handoff (skill)

Runs in your interactive session after writing-plans. It writes no factory state; its only output is one GitHub issue.

Preconditions (refuses with a specific reason if any fails):

- `factory/bin/job` exists in the project and `gh` is authenticated.
- Labels `factory` and `factory:planned` exist.
- The spec and plan are committed, and that commit is on `origin/<base>`. If not, it offers to push, and pushes only on your explicit yes.
- No open issue already carries a handoff block for the same plan path. If one does, it refuses and links it.

Then it proposes `risk` (`low` | `medium` | `high`) and `surfaces` (subset of `ui`, `security`) from the plan, with a one-line reason for each, and waits for your confirmation. It files the issue:

- Title: the plan's feature name, imperative.
- Labels: `factory`, `factory:planned`.
- Body: a short human-readable summary plus the handoff block:

````
```factory-plan
spec: docs/superpowers/specs/2026-11-12-dark-mode-design.md
plan: docs/superpowers/plans/2026-11-12-dark-mode.md
commit: <40-hex sha>
risk: medium
surfaces: [ui]
```
````

### Edits to the vendored factory

**`factory/bin/job` (Python, stdlib only)**

- New subcommand `planned <id>`, for a job in stage `intake` whose issue has the `factory:planned` label. It:
  1. Fetches the issue, checks it carries `factory:planned`, and parses exactly one `factory-plan` fenced block from its body.
  2. Validates strictly:
     - `spec` and `plan` are relative paths under `docs/superpowers/`, with no `..` segment.
     - `commit` is 40 lowercase hex characters and is an ancestor of `origin/<base>`.
     - Both paths exist at that commit.
     - `risk` is one of `low`, `medium`, `high`.
     - `surfaces` is a subset of `{ui, security}`; empty is allowed.
  3. Writes `intake.md` in the upstream format: a `## Summary`, `DECISION: ACCEPT`, risk, surfaces, and the source paths with the sha.
  4. Writes `spec.md` and `plan.md` into the job folder via `git show <sha>:<path>`. Their content comes from repo history, not from issue text.
  5. Sets `planned: true` in `job.json`, applies the same routing lookup as `factory/bin/route` in-process (calling `route` as a subprocess would deadlock on the job lock `job planned` holds), and advances `intake → spec → build` through the existing legal transitions, so the worktree creation and issue comment behave as upstream.
  6. Prints one line, e.g. `PLANNED: 004-dark-mode → build (code, ux, ui)`.
- On any validation failure: moves the job to `needs-human`, posts the reason on the issue, and prints `PLANNED: REFUSED <reason>`.
- New legal transition: `intake → needs-human`. Upstream has no such move; it's needed for the refusal path above.
- `needs-human → build` refuses when the job has no worktree (a refused planned job never reached build). Such a job can only be rejected; you fix the plan and hand off again.

**`.claude/skills/factory/SKILL.md` (orchestrator)**

- At the **intake** step: if the issue has `factory:planned`, run `factory/bin/job planned <id>` instead of spawning the `intake` agent. On `PLANNED:` go to **build**; on `PLANNED: REFUSED` the job is finished for this run.
- A guard near the top: `/factory` commands run this skill directly. Superpowers brainstorming does not apply to them, because the design already happened (planned issues) or happens in intake (other issues).

**`.claude/agents/builder.md`**

- Add `Skill` to `tools`.
- When `<job folder>/plan.md` exists, execute its tasks in order. One commit per task. Tick each task off in `build.md`. Record any departure from the plan under `## Deviations`, with the reason.
- Use `superpowers:test-driven-development` for every task, `superpowers:systematic-debugging` when the gate failed, and `superpowers:verification-before-completion` before writing `STATUS: READY`.
- If a plan task cannot be done as written, write `STATUS: BLOCKED` naming the task and the reason.
- If a Superpowers skill cannot be loaded, write `STATUS: BLOCKED` with that reason.
- In round 2 and later, address only the gate failure, review findings or feedback; do not re-execute the plan.

**`.claude/agents/reviewer-code.md`**

When `plan.md` exists, `VERDICT: CHANGES` if any of these hold: a plan task is not done, a deviation has no justification, or a task's behavior has no test.

**`.claude/agents/approver.md`**

When `plan.md` exists, ESCALATE if the plan is incomplete or any deviation's justification isn't convincing.

**`factory/config.json`**

Add `"planned": "factory:planned"` to `labels`.

Non-planned `factory` issues keep the upstream behavior unchanged.

## Error handling

| Where | Failure | Outcome |
|---|---|---|
| handoff | spec/plan not committed or not on `origin/<base>` | Refuses; offers to push, pushes only on an explicit yes. |
| handoff | factory not installed, `gh` not authenticated, labels missing | Refuses and names the `factory-install` step that fixes it. |
| handoff | an open issue already exists for this plan path | Refuses and links that issue. |
| `job planned` | invalid handoff block | `needs-human`; the reason is posted on the issue. |
| builder | plan task can't be done as written | `STATUS: BLOCKED` → `needs-human`. You fix the plan interactively, close the issue, and hand off again. |
| builder | Superpowers skill missing | `STATUS: BLOCKED` with the reason. |
| any | gate/review failures | Upstream behavior: up to `max_rounds`, then `needs-human`. |

The issue pins the commit sha, so later edits to the plan have no effect on a running job. To change course, close the issue and hand off again, or give `/factory` feedback on an escalated job.

### Trust boundary

`factory:planned`, like `factory`, can only be added by people with triage or write access. The handoff block is parsed only by `bin/job`, never placed in a prompt. Everything agents read as spec or plan comes from `git show` at a sha already on the base branch.

## Upstream updates

`vendor/factory/UPSTREAM` records the pinned sha. To update: diff upstream between the pinned sha and the new one, apply the changes to the vendored files by hand, and run the tests. No patch tooling.

## Testing

1. **`tests/test_job_planned.py`** (stdlib `unittest`, run against a temporary git repo with a bare `origin`; `gh` calls stubbed). One test per rule:
   - a valid block reaches `build` with `spec.md`, `plan.md` and `intake.md` written;
   - a missing block;
   - two blocks;
   - a path outside `docs/superpowers/`;
   - a path containing `..`;
   - a malformed sha;
   - a sha that is not an ancestor of base;
   - a path missing at the sha;
   - an unknown risk value;
   - an unknown surface.

   Each failure case ends in `needs-human`.
2. **End-to-end run** on a throwaway private GitHub repo with a tiny project, `concurrency: 1`, and every agent on Haiku:
   - one planned issue, expected to merge;
   - one ordinary `factory` issue, to confirm the upstream path still works;
   - one issue with a tampered block (sha not on base), expected to be refused.
3. **Handoff check**: in a fresh session, go brainstorming → writing-plans → `/factory-handoff`, then inspect the filed issue's labels and block.

## Out of scope

- Dependencies between issues, or parallel slices of one plan.
- Any change to Superpowers core.
- Publishing the plugin anywhere; it stays a local repo until you decide otherwise.
