# superpowers-factory

Design with [Superpowers](https://github.com/obra/superpowers), build with the
vendored software factory.

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

1. In the project, run `/factory-install` once and commit what it adds.
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

## Layout

- `skills/factory-install`, `skills/factory-handoff`: this plugin's skills.
- `vendor/factory/`: the upstream factory at the sha in `vendor/factory/UPSTREAM`,
  with edits to `factory/bin/job`, `factory/config.json`, the `factory` skill,
  and the builder, reviewer-code and approver agents. `git log -- vendor/` shows
  the unmodified import first, then each edit.

## Updating upstream

Diff upstream between the sha in `vendor/factory/UPSTREAM` and the new one,
apply the changes to `vendor/factory/` by hand, bump the sha, run the tests.

## License

GPLv3, because `vendor/factory/` is a modified copy of the GPLv3 upstream.
