# superpowers-factory

Design with [Superpowers](https://github.com/obra/superpowers).

You brainstorm and plan interactively. `/factory-handoff` turns the committed
spec and plan into one GitHub issue labeled `factory` + `factory:planned`.
`/factory run` then builds the whole plan on one branch, gates it with your
project's checks, reviews it, and merges it or hands it to you as one PR.

## Install the plugin

```text
/plugin marketplace add /Users/nandanthakur/projects/superpowers-factory
/plugin install superpowers-factory@superpowers-factory-dev
```

Superpowers must be installed too: the factory's builder uses its TDD,
debugging and verification skills.

## Use it in a project

1. In the project, run `/factory-install` once and commit what it adds. It
   also adds a Stop hook that runs `factory/checks.sh` before a session ends,
   a `CLAUDE.md` that imports `AGENTS.md`, and a CI workflow for the same
   checks. `factory/bin/doctor` checks the install at any time. Then start a
   fresh session: the factory's agents only load at session start.
2. `superpowers:brainstorming` → spec, `superpowers:writing-plans` → plan.
   When writing-plans offers an execution choice, run `/factory-handoff` instead.
3. In a fresh session, run `/factory run`.

## Flow

```
brainstorming → spec    writing-plans → plan    /factory-handoff → issue
/factory run: job planned → builder → gate → reviewers → approver → PR
```

Ordinary `factory` issues (without `factory:planned`) still go through the
upstream intake and spec-writer agents.

## Models and effort

Every agent's model and effort come from the project's `factory/config.json`;
no agent file names a model. `agents.intake` sets intake.
`routing.<low|medium|high>` sets the spec writer, builder, approver and code
reviewer for jobs of that risk, and `surface_reviewers` adds the UX, UI and
security reviewers. Models are aliases listed in `model_aliases`; efforts come
from `effort_levels`. To see what a role will run on:
`factory/bin/job agent <job> <role>`.

## PR comments

Comments on a factory PR reach the job's builder without `/factory`. The
factory reads conversation comments, inline review comments and reviews with a
body from the operator (the `gh` account running it) and the logins in
`factory/config.json` `pr_feedback.allowed`; bots and everyone else are
ignored. An escalated job resumes on the next `/factory run`; a running job
gets them in its next round; and the factory won't merge while a trusted
comment is unhandled. Merging the PR on GitHub stays the approval. An edit
counts only if a trusted person made it.

## Working on this repo

Agents and contributors: read `AGENTS.md`, and run `scripts/check` before
calling a change done. CI runs the same script.

## Layout

- `skills/factory-install`, `skills/factory-handoff`: this plugin's skills.
- `vendor/factory/`: the vendored factory (see `vendor/factory/NOTICE`),
  with edits to `factory/bin/job`, `factory/config.json`, the `factory` skill,
  and the builder, reviewer-code and approver agents. `git log -- vendor/` shows
  the unmodified import first, then each edit.

## Updating the vendored factory

The first commit in `git log -- vendor/factory` is the unmodified import. To
take a newer version, diff it against that import, apply the changes to
`vendor/factory/` by hand, and run the tests.

## License

GPLv3, because `vendor/factory/` is a modified copy of GPLv3-licensed code.
