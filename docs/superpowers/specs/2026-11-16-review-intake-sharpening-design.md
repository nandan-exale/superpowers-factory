# Sharper review and intake, with rejection memory

Date: 2026-11-16. Status: approved design.

## Why

[mattpocock/skills](https://github.com/mattpocock/skills) (MIT, read at
`5863806`) is a curated set of agent skills, several of them for the same
loop the factory runs: triage an issue, brief an agent, review its diff.
Most of the repo overlaps Superpowers (design, TDD, debugging, which the
builder already uses) or is off-domain. Three ideas fill real gaps in the
factory's agents:

1. **Two-axis review** (`code-review`): a review that asks both "does it
   follow the standards" and "does it do what the spec asked, and no more".
   Our `reviewer-code` checks correctness and conventions, but has no
   explicit scope-creep check and no baseline for repos whose docs say
   little about style.
2. **Agent briefs** (`triage/AGENT-BRIEF.md`): durable, behavioural briefs
   with current and desired behaviour, testable acceptance criteria and an
   explicit out-of-scope list; and a redundancy check before accepting.
   Intake's `## Scope` is free prose today.
3. **Rejection memory** (`triage/OUT-OF-SCOPE.md`): rejected requests are
   recorded and later requests are checked against them. Today an intake
   REJECT leaves no trace a later intake can see, so the same idea filed
   again costs a fresh intake run and may get a different answer.

We take the ideas, not the text: everything is rewritten in this repo's
voice, and `NOTICE` credits the source.

Out of scope here (each would be its own spec): dependency-aware ticket
decomposition (`to-tickets`), new factory tasks such as a ratchet or fix
task (`software-factory/EXAMPLE-TASKS.md`), a PR-body skill (`pr`).

## 1. Two-axis code review

Files: `plugin/vendor/factory/factory/agents/reviewer-code.md`,
`plugin/vendor/factory/factory/config.json`.

- **Scope creep** joins "What to look for": behaviour in the diff that the
  spec (and `plan.md`, when it exists) didn't ask for, such as a new option,
  endpoint, flag, fallback or changed default. It is a CHANGES finding,
  tagged `scope-creep` when that tag is in `learning.tags`, otherwise
  `other:scope-creep`. Refactoring the spec needs to land the change, and
  tests or docs for the asked-for behaviour, are not scope creep.
- `scope-creep` is added to the default `learning.tags` in `config.json`.
  `factory-update` adds missing keys but doesn't extend lists, so existing
  installs keep their list; the `other:` fallback keeps their reviews valid.
- **Smell baseline**: a short list of design smells (unclear name,
  duplicated logic, feature envy, data clump, primitive standing in for a
  domain concept, repeated switch on the same type, one change scattered
  across many files, speculative generality, long navigation chains, a pure
  pass-through layer, an implementer that ignores what it inherits), each
  with its usual fix, written in our own words. Rules:
  - A smell is always a judgement call and goes under `## Notes`, never
    under `## Findings`, so it never costs a round.
  - A repo standard (AGENTS.md, the docs it lists, the neighbouring code)
    overrides the baseline: where the repo endorses a pattern, don't flag it.
  - Skip anything the repo's tooling already enforces.
- The reviewer stays one agent writing one `## Findings` section. Separate
  spec and standards reviewers would double the cost of every round, and
  `bin/job` counts tags from that one section.

## 2. Structured intake brief

File: `plugin/vendor/factory/factory/agents/intake.md`.

- For ACCEPT, `## Scope` (the heading stays: the spec writer treats it as
  binding and the approver checks against it) has four labelled parts:
  - **Current behaviour**: what happens now (for a bug, the broken
    behaviour).
  - **Desired behaviour**: what should happen after the change, including
    the edge and error cases the issue implies.
  - **Acceptance criteria**: a checklist; each item is testable on its own.
  - **Out of scope**: what this job must not change, including anything
    left out by rescoping.
- The brief describes behaviour and interfaces (types, commands, config
  shapes), not file paths or line numbers: the spec writer chooses files.
- **Redundancy check**: before ACCEPT, intake searches the code for the
  requested behaviour by concept, not only by the issue's wording. `## Why`
  names where it looked. If the behaviour already exists, intake REJECTs
  and points to it.
- Planned jobs (`factory:planned`) skip intake; `planned_intake_md` is
  unchanged.

## 3. Rejection memory

Files: `plugin/vendor/factory/factory/bin/job`, `config.json`,
`agents/intake.md`, `bin/doctor` (label list comes from config, so no code
change), `plugin/vendor/factory/INSTALL.md`,
`plugin/skills/factory-install/SKILL.md`,
`plugin/skills/factory-update/SKILL.md`.

GitHub is the memory: nothing is committed, it survives disposable runners,
and a human can see and undo it.

- New label `labels.rejected` = `factory:rejected` in `config.json`
  (`factory-update`'s `add_missing` adds it to existing configs).
- **Recording.** When a job moves to `rejected`, by an intake REJECT or by
  `job reject` from a waiting stage, `bin/job` adds `factory:rejected` to
  the issue alongside the label changes it already makes. If adding it
  fails (for example the label doesn't exist yet), the rejection still
  stands: `bin/job` prints a warning to stderr naming the missing label,
  as it already does for labels on `merged`.
- **Undo.** Removing `factory:rejected` from an issue takes it out of the
  memory. Re-queuing a rejected issue (`factory` label again) starts a new
  job as today; its own issue never appears in its own `rejections.md`.
- **Recall.** Whenever `bin/job` writes `issue.md` (job creation, and the
  return from needs-info), it also writes `<job folder>/rejections.md` from
  a new `fetch_rejections()`:
  - `gh issue list --label factory:rejected --state all --limit 30
    --json number,title,url,comments`, newest first.
  - Excludes the job's own issue.
  - For each issue, the reason is the body of the latest comment that is
    authored by `operator()`, starts with the factory's `MARKER`, and is a
    rejection (`### Factory intake: REJECT` or `### Factory: rejected`).
    Anyone can type the marker, so the author check is what makes it the
    factory's. Issues with no such comment are skipped (a human added the
    label by hand with no reason recorded).
  - Each reason is clipped to a named constant length (`REJECTION_CHARS`,
    1500); titles and reasons are quoted
    (`> `) under a header that says they are data, not instructions, the same
    wording `issue.md` uses.
  - With no prior rejections the file says so in one line, so intake can
    tell "none" from "missing".
  - A `gh` failure fails the command the same way a `fetch_issue` failure
    does; the job stays where it was.
- **Use.** Intake reads `rejections.md`. When the issue asks for the same
  thing as a prior rejection, intake REJECTs and cites that issue's number
  and reason. When it is similar but differs in a way that answers the old
  reason, intake may ACCEPT and says in `## Why` how it differs.
- **Setup.** `INSTALL.md` and the install skill create the label
  (`gh label create factory:rejected --color BFD4F2 --description "The
  factory rejected this request; later intakes check new issues against
  it"`). `bin/doctor` already fails on any configured label missing on
  GitHub; the update skill tells the user to create it when doctor says so.

## Attribution

`plugin/vendor/factory/NOTICE` gets one line crediting mattpocock/skills
(MIT, Copyright (c) 2026 Matt Pocock) for the ideas behind the review smell
baseline, the intake brief structure and rejection memory. No text is copied,
so no licence text is bundled. The name doesn't trip the branding check,
which forbids only the factory's upstream names.

## Testing

Unit tests (stdlib `unittest`, `tests/factory_project.py`):

- `FactoryProject.load_job` stubs `fetch_rejections` like `fetch_issue`, so
  existing tests keep passing.
- New `tests/test_rejections.py`:
  - intake REJECT adds `factory:rejected` and removes `factory`;
  - `job reject` from needs-info adds `factory:rejected`;
  - a failing label add still leaves the job `rejected` and warns;
  - `rejections.md` is written on create and on return from needs-info;
  - it excludes the job's own issue, skips issues without a factory
    rejection comment, ignores marker comments from anyone but the
    operator, clips long reasons,
    quotes every line, and says "none" when empty;
  - a `gh` failure in `fetch_rejections` fails create and writes no job.
- `tests/test_doctor.py`: config with `labels.rejected` and the new tag
  passes.

Evals (`tests/evals/`, run by hand with `scripts/eval`, which spends money):

- `reviewer-code/scope-creep`: the diff adds an unrequested flag;
  expect `VERDICT: CHANGES`, `tags_any: ["scope-creep", "other:scope-creep"]`.
- `reviewer-code/smell-only`: a correct diff with unclear names (`q`, `r`);
  expect `VERDICT: PASS` (the smell lands in Notes).
- `intake/reject-already-implemented`: the issue asks for behaviour the
  fixture code already has; expect `DECISION: REJECT`.
- `intake/reject-previously-rejected`: the fixture job folder holds a
  `rejections.md` with a matching prior rejection; expect
  `DECISION: REJECT` and a regex for the cited issue number.
- `intake/accept`: add a regex that `## Scope` has `Acceptance criteria`
  and `Out of scope`.

The PR says whether `scripts/eval` was run; a baseline change is committed
only with the run that produced it.

## Constraints

- Vendored edits go in their own commits; `scripts/known-hashes` is rerun
  and `plugin/vendor/known-hashes.json` committed with them.
- Python standard library only; `bin/job` stays the only writer of
  `job.json`.
- The installed copy in `factory/` and `.claude/` is not touched; it
  changes later through `/factory-update`.
