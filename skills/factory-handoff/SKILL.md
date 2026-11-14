---
name: factory-handoff
description: Use after superpowers:writing-plans when the user wants the software factory to build the plan unattended instead of executing it in this session. Files one GitHub issue labeled factory + factory:planned that points at the committed spec and plan.
---

# Factory handoff

Hand one approved Superpowers spec + plan to the software factory. Your only
output is one GitHub issue. You never write anything under `factory/`, never
start `/factory run`, and never edit the spec or plan.

Announce: "I'm using factory-handoff to file this plan for the factory."

## 1. Find the spec and plan

Use the spec and plan from this conversation. If there are none, take the
newest file in `docs/superpowers/specs/` and in `docs/superpowers/plans/`.
Show both paths and ask your human partner to confirm before going on.

## 2. Check, and stop with the reason if anything fails

Run each check. On the first failure, say which one failed and what fixes it,
then stop.

```bash
test -x factory/bin/job                       # else: run /factory-install in this project
gh auth status                                # else: gh auth login
gh label list --limit 200 --json name --jq '.[].name' | grep -qx factory
gh label list --limit 200 --json name --jq '.[].name' | grep -qx factory:planned
                                              # either missing: re-run /factory-install
BASE=$(python3 -c 'import json; print(json.load(open("factory/config.json"))["base_branch"])')
git status --porcelain -- <spec> <plan>       # must print nothing: commit them first
git cat-file -e HEAD:<spec>                   # each must succeed, else the file is
git cat-file -e HEAD:<plan>                   # gitignored or uncommitted: commit it
git fetch origin "$BASE"
git merge-base --is-ancestor HEAD "origin/$BASE"
```

If the last check fails, the spec and plan aren't on `origin/$BASE` yet. If
the current branch is `$BASE`, ask: "Push `$BASE` to origin so the factory
can see the plan?" Run `git push origin "$BASE"` only on an explicit yes. On
any other branch, say the plan must reach `$BASE` first (merge it or open a
PR) and stop.

Both paths must match `^docs/superpowers/[A-Za-z0-9._/-]+\.md$` and contain
no `..` segment. The factory refuses anything else, so move the files there
first.

Check that no open issue already hands off this plan:

```bash
gh issue list --label factory:planned --state open --search "\"<plan path>\" in:body" --json number,url
```

If it prints any issue, link it and stop.

Check the plan for steps a factory job can't do: it works only on its own
branch in its own worktree.

```bash
grep -nE 'git tag|git push|--force|git checkout (main|master|"?\$BASE)|git merge' <plan>
```

If anything matches other than pushing the plan's own feature branch, show
the lines and say the factory will skip them and list them for the human
under `## Deviations`. Ask whether to file anyway or fix the plan first.

Then record the commit: `SHA=$(git rev-parse HEAD)`.

## 3. Propose risk and surfaces

Read the spec and plan and propose:

- **Risk**: `low` (contained change, easy to verify, nothing sensitive),
  `medium` (several files or behaviours, or shared code), or `high` (data,
  money, auth, migrations, concurrency, or anything hard to undo).
- **Surfaces**: `ui` if a user will see the change on a page or screen;
  `security` if it touches auth, permissions, user input reaching queries,
  shells or HTML, secrets, or payments. Both, one, or none.

Give one line of reasoning for each and ask your human partner to confirm or
change them. Don't file anything until they confirm.

Then read the ESCALATE lists in `factory/agents/approver.md` (the general
list and any "In this project" list). If the plan clearly changes something
on them, tell your human partner which rule, and that the approver will
escalate, so the job will stop at needs-human for you to merge. This is
information only; it doesn't stop the handoff.

## 4. Split a large plan into parts

Count the plan's tasks (`### Task <n>` headings). Read
`handoff.max_tasks_per_part` from `factory/config.json` (8 when it's
missing). If the plan has more tasks than that, or your human partner asks
for parts, propose a split: consecutive task ranges, each ending where the
tests pass and the change can be reviewed on its own, none over the cap.
Show each part's range and one line on what it delivers, and ask them to
confirm or edit the split. Don't split a plan they want built as one PR.

Parts build one after another, never stacked: part `k` starts only after
part `k-1`'s PR has merged, so expect one PR at a time.

## 5. File the issue

Title: the plan's feature name as a short imperative ("Add dark mode"). Write
the body to a temp file, then create the issue:

````markdown
<two or three sentences: what this builds and why, from the spec>

Spec and plan were approved with Superpowers; the factory builds the plan as written.

```factory-plan
spec: <spec path>
plan: <plan path>
commit: <SHA>
risk: <risk>
surfaces: [<surfaces, comma-separated, or nothing>]
```
````

```bash
gh issue create --title "<title>" --label factory --label factory:planned --body-file <temp file>
```

The block must be exactly as above: five `key: value` lines (three more for
a part, below), paths relative to the repo root, the full 40-character sha.
`factory/bin/job planned` refuses anything else.

For a split plan, file one issue per part, in order, and wait for each
`gh issue create` to print its URL before filing the next. Every part gets
the same `spec`, `plan`, `commit`, `risk` and `surfaces`, plus:

```
part: <k>/<n>
tasks: <first>-<last>
depends: #<previous part's issue>
```

Leave `depends` out of part 1. Title each `<title> (part <k>/<n>)`. Label
every part `factory` and `factory:planned`: the factory holds a part until
the part it depends on has merged.

File the issue as yourself (the account `gh auth status` shows): `factory/bin/job planned` refuses planned issues whose author isn't the account running the factory.

## 6. Report

For a split plan, list every part's issue URL in order.

Give the issue URL and say: "Run `/factory run <n>` (or `/factory run`) in a
fresh session in this project. The plan is pinned to `<short SHA>`; later
edits to it won't reach this job."
