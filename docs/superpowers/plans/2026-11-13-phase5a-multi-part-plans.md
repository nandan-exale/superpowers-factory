# Phase 5a: Multi-Part Plans Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A plan too big for one PR is handed off as ordered parts, one issue and one PR each. A part starts only after the previous part has merged, and each part's builder carries out only its task range.

**Architecture:**
- **Plugin `factory-handoff` skill:** counts the plan's tasks. Above `handoff.max_tasks_per_part` (default 8), or on request, it proposes consecutive task ranges and files one issue per part in order. Each block adds `part: k/n`, `tasks: N-M` and `depends: #<previous part's issue>`.
- **Vendored `job`:** `parse_plan_block` accepts the three optional keys. `job queue` keeps a part waiting (`wait … depends #N`) until its dependency's job is merged. `job planned` checks the range against the plan, refuses a part whose dependency failed (the existing refusal path, so it goes to needs-human), and records `part` and `tasks` in `job.json` and `intake.md`.
- **Vendored skill and prompts:** the job header gains `Tasks: N-M of T.`. The builder does only those tasks, and reviewers and the approver judge plan conformance against the range.

**Tech Stack:** Python 3.10+ stdlib, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-13-phase5-scale-design.md` (section 5a)

**Rules for this plan:**
- Never edit the spec or this plan. Make no git tags. Push nothing but the job branch.
- Each vendored edit in its own commit, then the plugin side with tests and the refreshed `vendor/known-hashes.json` (`scripts/known-hashes`).
- Change nothing in the installed copy (`factory/`, `.claude/` at the repo root).
- Old configs keep working: read `handoff` with a default of 8.
- Built after Phase 4 is merged. Anchor every edit on function and heading names; line numbers will have moved.
- One deviation from the spec's literal text: the spec says a part whose dependency failed "goes to needs-human". A job only exists once the queue starts it. So the queue lets such a part start (`new`), and `job planned` refuses it with the spec's message. That is the existing refusal path, so it lands in `needs-human`.
- Full check: `scripts/check`.

---

### Task 1: The plan block accepts `part`, `tasks` and `depends`

**Files:**
- Modify: `vendor/factory/factory/bin/job` (`PLAN_KEYS`, `parse_plan_block`)
- Test: `tests/test_parse_plan_block.py`

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_parse_plan_block.py` (it already loads the vendored `job`; reuse its helper that builds a block. If it builds blocks inline, build them the same way):

```python
class PartKeysTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.job = FactoryProject(tmp.name).load_job()

    def block(self, extra=""):
        return ("```factory-plan\nspec: docs/superpowers/specs/a.md\nplan: docs/superpowers/plans/a.md\n"
                f"commit: {'a' * 40}\nrisk: medium\nsurfaces: []\n{extra}```\n")

    def test_part_tasks_and_depends(self):
        plan = self.job.parse_plan_block(self.block("part: 2/3\ntasks: 4-7\ndepends: #41\n"))
        self.assertEqual((plan["part"], plan["tasks"], plan["depends"]), ((2, 3), (4, 7), 41))

    def test_whole_plan_has_none_of_them(self):
        plan = self.job.parse_plan_block(self.block())
        self.assertNotIn("part", plan)

    def test_bad_values_are_refused(self):
        for extra, message in (("part: 4/3\ntasks: 1-2\n", "part"),
                               ("part: 1/2\ntasks: 5-2\n", "tasks"),
                               ("part: 1/2\n", "together"),
                               ("part: 1/2\ntasks: 1-3\ndepends: #4\n", "part 1"),
                               ("part: 2/2\ntasks: 4-6\n", "depends"),
                               ("part: 2/2\ntasks: 4-6\ndepends: 41\n", "depends")):
            with self.assertRaisesRegex(self.job.Refused, message, msg=extra):
                self.job.parse_plan_block(self.block(extra))
```

(Add `import tempfile` and `from factory_project import FactoryProject` if the file lacks them.)

- [ ] **Step 2: Run them and see them fail.** `python3 -m unittest tests/test_parse_plan_block.py -v`

- [ ] **Step 3: Implement.** In `job`, next to `PLAN_KEYS`:

```python
PLAN_PART_KEYS = {"part", "tasks", "depends"}
```

In `parse_plan_block`, replace

```python
    require(set(fields) == PLAN_KEYS,
            f"factory-plan needs exactly {', '.join(sorted(PLAN_KEYS))}; got {', '.join(sorted(fields))}")
```

with

```python
    required, optional = set(fields) & PLAN_KEYS, set(fields) - PLAN_KEYS
    require(required == PLAN_KEYS and optional <= PLAN_PART_KEYS,
            f"factory-plan needs {', '.join(sorted(PLAN_KEYS))} (and optionally part, tasks, depends); "
            f"got {', '.join(sorted(fields))}")
```

and change the final `return` to:

```python
    plan = {**{k: fields[k] for k in PLAN_KEYS}, "surfaces": surfaces}
    plan.update(parse_part(fields))
    return plan
```

Add after `parse_plan_block`:

```python
def parse_part(fields):
    """{} for a whole plan; else {part: (k, n), tasks: (first, last), depends: issue or None}."""
    if not set(fields) & PLAN_PART_KEYS:
        return {}
    require("part" in fields and "tasks" in fields, "part and tasks go together in a factory-plan block")
    m = re.fullmatch(r"(\d+)/(\d+)", fields["part"])
    require(m and 1 <= int(m.group(1)) <= int(m.group(2)), f"part must be k/n with 1 ≤ k ≤ n: {fields['part']!r}")
    k, n = int(m.group(1)), int(m.group(2))
    t = re.fullmatch(r"(\d+)-(\d+)", fields["tasks"])
    require(t and 1 <= int(t.group(1)) <= int(t.group(2)), f"tasks must be N-M with 1 ≤ N ≤ M: {fields['tasks']!r}")
    depends = fields.get("depends")
    if k == 1:
        require(depends is None, "part 1 has no depends")
    else:
        d = re.fullmatch(r"#(\d+)", depends or "")
        require(d, f"part {k} needs depends: #<issue of part {k - 1}>, got {depends!r}")
        depends = int(d.group(1))
    return {"part": (k, n), "tasks": (int(t.group(1)), int(t.group(2))), "depends": depends}
```

- [ ] **Step 4: Run them and see them pass**, plus `python3 -m unittest tests/test_job_planned.py -v`.

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/factory/bin/job
git commit -m "feat(vendor): factory-plan blocks accept part, tasks and depends"
scripts/known-hashes
git add tests/test_parse_plan_block.py vendor/known-hashes.json
git commit -m "test: plan block part keys; refresh known hashes"
```

---

### Task 2: The queue waits for a part's dependency

**Files:**
- Modify: `vendor/factory/factory/bin/job` (`cmd_queue`, new `dependency_state`)
- Create: `tests/test_parts.py`

- [ ] **Step 1: Write the failing tests.** `tests/test_parts.py`:

```python
import contextlib
import io
import json
import unittest

from budget_case import BudgetCase

BODY = ("Part.\n\n```factory-plan\nspec: docs/superpowers/specs/2026-11-12-widget-design.md\n"
        "plan: docs/superpowers/plans/2026-11-12-widget.md\ncommit: {sha}\nrisk: medium\nsurfaces: []\n"
        "part: 2/2\ntasks: 1-1\ndepends: #7\n```\n")


class QueueDependsTest(BudgetCase):
    def setUp(self):
        super().setUp()
        self.dep_state = "OPEN"
        base = self.fake_gh_json

        def gh_json(*args):
            if args[:2] == ("issue", "view"):
                return {"state": self.dep_state}
            return base(*args)

        self.job.gh_json = gh_json
        self.issues = [{"number": 9, "title": "Widget (part 2/2)", "body": BODY.format(sha=self.project.sha),
                        "labels": [{"name": "factory"}, {"name": "factory:planned"}]}]

    def queue(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_queue()
        return [l.split("\t") for l in out.getvalue().splitlines()]

    def row(self, n):
        return next(r for r in self.queue() if r[1] == str(n))

    def test_waits_while_part_one_is_open(self):
        row = self.row(9)
        self.assertEqual((row[0], row[-1]), ("wait", "depends #7"))

    def test_starts_once_part_one_merged(self):
        job = self.job.load(self.job_id)
        job.update(stage="merged")
        self.job.save(job)
        self.dep_state = "CLOSED"
        self.assertEqual(self.row(9)[0], "new")

    def test_a_failed_dependency_starts_so_planned_can_refuse_it(self):
        job = self.job.load(self.job_id)
        job.update(stage="rejected")
        self.job.save(job)
        self.assertEqual(self.job.dependency_state(7, {7: job}), "failed")
        self.assertEqual(self.row(9)[0], "new")

    def test_closed_without_a_merged_job_is_failed(self):
        self.dep_state = "CLOSED"
        self.assertEqual(self.job.dependency_state(7, {}), "failed")
```

(`BudgetCase` creates the job for issue 7 in `setUp`; `self.issues` feeds `gh issue list`.)

- [ ] **Step 2: Run them and see them fail.** `python3 -m unittest tests/test_parts.py -v`

- [ ] **Step 3: Implement.** In `job`, add before `cmd_queue`:

```python
def dependency_state(issue, jobs):
    """merged | failed | pending for the part a planned issue depends on. `jobs` maps issue → job."""
    job = jobs.get(issue)
    if job and job["stage"] == "merged":
        return "merged"
    if job and job["stage"] == "rejected":
        return "failed"
    state = gh_json("issue", "view", str(issue), "--json", "state")["state"]
    return "failed" if state == "CLOSED" else "pending"


def planned_depends(issue):
    """The issue a planned part waits for, or None (also when the block is malformed: `job planned` reports that)."""
    if LABELS["planned"] not in {l["name"] for l in issue.get("labels", [])}:
        return None
    try:
        return parse_plan_block(issue.get("body", "")).get("depends")
    except Refused:
        return None
```

In `cmd_queue`, change the `gh issue list` call's `--json` fields to `number,title,body,labels`, and change

```python
        if not j:
            new_rows.append(("new", n, "-", "-", issue["title"]))
```

to

```python
        if not j:
            dep = planned_depends(issue)
            if dep and dependency_state(dep, jobs) == "pending":
                other_rows.append(("wait", n, "-", "-", f"depends #{dep}"))
            else:
                new_rows.append(("new", n, "-", "-", issue["title"]))
```

- [ ] **Step 4: Run them and see them pass**, plus `python3 -m unittest tests/test_budgets.py tests/test_run_fixes.py -v` (the queue's other rows must not change).

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/factory/bin/job
git commit -m "feat(vendor): job queue holds a plan part until the part it depends on merges"
scripts/known-hashes
git add tests/test_parts.py vendor/known-hashes.json
git commit -m "test: queue waits on plan part dependencies; refresh known hashes"
```

---

### Task 3: `job planned` checks the range and records it

**Files:**
- Modify: `vendor/factory/factory/bin/job` (`cmd_planned`, `planned_intake_md`)
- Test: `tests/test_parts.py`

Rules:
- The plan's task count is the number of `### Task <n>` headings in the plan at the pinned commit. `tasks` must end at or before it: `tasks 4-14 is past the plan's 12 tasks`.
- With `depends`: `dependency_state` must be `merged`. `failed` → refuse with `part <k-1> (#<dep>) didn't merge; re-plan or remove the dependency`. `pending` → refuse with `part <k-1> (#<dep>) hasn't merged yet` (the queue normally prevents this).
- Each refusal goes through the existing `except Refused` path, so the job lands in `needs-human`.
- On success, `job.json` gets `"part": "2/3"`, `"tasks": "4-7"`, `"plan_tasks": 12`. `intake.md`'s `## Scope` gets this paragraph: "This is part 2 of 3: build only tasks 4-7 of 12. Earlier tasks are already merged on the base branch; later parts build the rest."

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_parts.py`:

```python
PLAN = "# Widget plan\n\n### Task 1: Spin\n\n### Task 2: Stop\n\n### Task 3: Wobble\n"


class PlannedPartTest(BudgetCase):
    def setUp(self):
        super().setUp()
        repo = self.project.repo
        (repo / "docs/superpowers/plans/2026-11-12-widget.md").write_text(PLAN)
        from factory_project import git
        git(repo, "commit", "-qam", "three tasks")
        git(repo, "push", "-q", "origin", "main")
        self.sha = git(repo, "rev-parse", "HEAD")
        self.dep = {"stage": "merged"}
        self.job.dependency_state = lambda issue, jobs: self.dep["stage"]

    def planned(self, extra):
        body = BODY.format(sha=self.sha).replace("part: 2/2\ntasks: 1-1\ndepends: #7\n", extra)
        self.project.set_issue(body, labels=("factory", "factory:planned"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_planned(self.job.sync(self.job.load(self.job_id)))
        return out.getvalue(), json.loads((self.d / "job.json").read_text())

    def test_records_the_range(self):
        out, job = self.planned("part: 2/2\ntasks: 2-3\ndepends: #5\n")
        self.assertIn("PLANNED:", out)
        self.assertEqual((job["part"], job["tasks"], job["plan_tasks"]), ("2/2", "2-3", 3))
        self.assertIn("build only tasks 2-3 of 3", (self.d / "intake.md").read_text())

    def test_range_past_the_plan_is_refused(self):
        out, job = self.planned("part: 1/2\ntasks: 1-4\n")
        self.assertIn("PLANNED: REFUSED tasks 1-4 is past the plan's 3 tasks", out)
        self.assertEqual(job["stage"], "needs-human")

    def test_failed_dependency_is_refused(self):
        self.dep["stage"] = "failed"
        out, job = self.planned("part: 2/2\ntasks: 2-3\ndepends: #5\n")
        self.assertIn("part 1 (#5) didn't merge; re-plan or remove the dependency", out)
        self.assertEqual(job["stage"], "needs-human")
```

(`BudgetCase`'s project uses the operator `operator` and `fetch_issue` returns `self.project.issue`, so `job planned` runs offline. If `cmd_planned` needs `route_agents` inputs from config, the vendored config already has them.)

- [ ] **Step 2: Run them and see them fail.**

- [ ] **Step 3: Implement.** In `cmd_planned`, inside the `try:` after `check_plan_commit(plan)`, add:

```python
        plan_text = run(["git", "show", f"{plan['commit']}:{plan['plan']}"]).stdout
        check_part(plan, plan_text, {j["issue"]: j for j in read_jobs()})
```

and after the `try/except`, use `plan_text` for `plan.md` instead of reading it again (keep the existing loop for `spec`). Add before `cmd_planned`:

```python
TASK_HEADING = re.compile(r"^### Task \d+", re.M)


def check_part(plan, plan_text, jobs):
    """Refuse a part whose range is past the plan or whose dependency hasn't merged."""
    if "part" not in plan:
        return
    total = len(TASK_HEADING.findall(plan_text))
    first, last = plan["tasks"]
    require(last <= total, f"tasks {first}-{last} is past the plan's {total} tasks")
    plan["plan_tasks"] = total
    dep = plan["depends"]
    if dep:
        state = dependency_state(dep, jobs)
        k = plan["part"][0]
        require(state != "failed", f"part {k - 1} (#{dep}) didn't merge; re-plan or remove the dependency")
        require(state == "merged", f"part {k - 1} (#{dep}) hasn't merged yet")
```

Where `cmd_planned` builds the new job dict (`job = {**sync(job), "planned": True, "plan_paths": ..., ...}`), add the part fields when present:

```python
    if "part" in plan:
        k, n = plan["part"]
        first, last = plan["tasks"]
        job.update(part=f"{k}/{n}", tasks=f"{first}-{last}", plan_tasks=plan["plan_tasks"])
```

In `planned_intake_md`, after the `## Scope` paragraph, add:

```python
    part = ""
    if "part" in plan:
        (k, n), (first, last) = plan["part"], plan["tasks"]
        part = (f"\nThis is part {k} of {n}: build only tasks {first}-{last} of {plan['plan_tasks']}. "
                "Earlier tasks are already merged on the base branch; later parts build the rest.\n")
```

and insert `part` into the returned text right after the Scope paragraph (before `"\n## Why\n"`). Because `check_part` sets `plan["plan_tasks"]` before `planned_intake_md` runs, the order in `cmd_planned` stays: check, then write files.

- [ ] **Step 4: Run them and see them pass**, plus `python3 -m unittest tests/test_job_planned.py -v`.

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/factory/bin/job
git commit -m "feat(vendor): job planned checks a part's task range and dependency and records them"
scripts/known-hashes
git add tests/test_parts.py vendor/known-hashes.json
git commit -m "test: planned parts; refresh known hashes"
```

---

### Task 4: Header and prompts

**Files:**
- Modify: `vendor/factory/.claude/skills/factory/SKILL.md`, `vendor/factory/.claude/agents/builder.md`, `vendor/factory/.claude/agents/reviewer-code.md`, `vendor/factory/.claude/agents/approver.md`
- Create: `tests/test_parts_wording.py`

- [ ] **Step 1: Write the failing test.** `tests/test_parts_wording.py`:

```python
import unittest
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[1] / "vendor/factory/.claude"


class PartsWordingTest(unittest.TestCase):
    def test_header_carries_the_range(self):
        self.assertIn("Tasks: <tasks> of <plan_tasks>.", (VENDOR / "skills/factory/SKILL.md").read_text())

    def test_builder_does_only_its_range(self):
        self.assertIn("carry out only the tasks in `Tasks:`", (VENDOR / "agents/builder.md").read_text())

    def test_reviewer_and_approver_judge_the_range(self):
        for name in ("reviewer-code", "approver"):
            self.assertIn("only the tasks in `Tasks:`", (VENDOR / f"agents/{name}.md").read_text(), name)
```

- [ ] **Step 2: Run it and see it fail.**

- [ ] **Step 3: Edit the texts.**

`SKILL.md`, right after the header code block (`Job: <id>. Job folder: … Issue: #<issue>.`), add:

```markdown
When `job.json` has `tasks` (a part of a larger plan), append
` Tasks: <tasks> of <plan_tasks>.` to the header, for example
`Tasks: 4-7 of 12.`
```

`builder.md`, **Planned jobs**, add a bullet after the "Round 1: carry out the plan's tasks in order…" bullet:

```markdown
- When the header has `Tasks: N-M of T.`, this job is one part of the plan:
  carry out only the tasks in `Tasks:`. Earlier tasks are already merged on
  the base branch; don't start later ones. `## Plan tasks` in build.md lists
  only your range.
```

`reviewer-code.md`, at the end of the **Plan** bullet under **What to look for**, add: "When the header has `Tasks: N-M of T.`, judge only the tasks in `Tasks:`; earlier ones are already on the base branch and later ones belong to other parts."

`approver.md`, at the end of the `plan.md` bullet under **Decide** (the one starting "When `plan.md` exists: every plan task is ticked"), add: "For a part (`Tasks: N-M of T.` in the header), only the tasks in `Tasks:` count."

- [ ] **Step 4: Run it and see it pass**, then `scripts/check --fast`.

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/.claude/skills/factory/SKILL.md
git commit -m "feat(vendor): the job header names a part's task range"
git add vendor/factory/.claude/agents/builder.md vendor/factory/.claude/agents/reviewer-code.md vendor/factory/.claude/agents/approver.md
git commit -m "feat(vendor): builder, reviewer and approver work on a part's range only"
scripts/known-hashes
git add tests/test_parts_wording.py vendor/known-hashes.json
git commit -m "test: part range wording; refresh known hashes"
```

---

### Task 5: `/factory-handoff` splits large plans

**Files:**
- Modify: `skills/factory-handoff/SKILL.md`, `vendor/factory/factory/config.json`
- Test: `tests/test_handoff_skill.py`

- [ ] **Step 1: Write the failing test.** Append to the test class in `tests/test_handoff_skill.py`:

```python
    def test_splits_large_plans_into_parts(self):
        text = (Path(__file__).resolve().parents[1] / "skills/factory-handoff/SKILL.md").read_text()
        for needle in ("handoff.max_tasks_per_part", "part: <k>/<n>", "tasks: <first>-<last>",
                       "depends: #<previous part's issue>", "(part <k>/<n>)", "one issue per part, in order"):
            self.assertIn(needle, text)
```

- [ ] **Step 2: Run it and see it fail.**

- [ ] **Step 3: Config.** In `vendor/factory/factory/config.json`, add after `digest`:

```json
  "handoff": { "max_tasks_per_part": 8 },
```

and in `vendor/factory/factory/bin/doctor` `check_config`, before the learner check:

```python
    handoff = cfg.get("handoff")
    if handoff is not None:
        cap = handoff.get("max_tasks_per_part") if isinstance(handoff, dict) else None
        if isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0:
            problems.append(fail("handoff.max_tasks_per_part must be a positive integer"))
```

- [ ] **Step 4: The skill.** In `skills/factory-handoff/SKILL.md`, add a section between **3. Propose risk and surfaces** and **4. File the issue**, and renumber the later sections:

```markdown
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
```

In **File the issue**, add after the block description:

````markdown
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
````

In **Report**, add: "For a split plan, list every part's issue URL in order."

- [ ] **Step 5: Run it and see it pass**, then `scripts/check`.

- [ ] **Step 6: Commit.**

```bash
git add vendor/factory/factory/config.json vendor/factory/factory/bin/doctor
git commit -m "feat(vendor): handoff.max_tasks_per_part in config, checked by doctor"
scripts/known-hashes
git add skills/factory-handoff/SKILL.md tests/test_handoff_skill.py vendor/known-hashes.json
git commit -m "feat: factory-handoff splits large plans into ordered parts"
```

---

### Task 6: README

- [ ] **Step 1:** In `README.md`, in the section that explains `/factory-handoff` (under **Everyday use**), add:

```markdown
**Large plans.** When a plan has more tasks than
`handoff.max_tasks_per_part` (8 by default), `/factory-handoff` proposes
splitting it into parts and files one issue per part, in order. Each part is
its own PR, carrying out only its task range. A part waits
(`wait … depends #N` in `job queue`) until the part before it has merged; if
that part is rejected or its issue is closed unmerged, the next part stops at
`needs-human` so you can re-plan.
```

- [ ] **Step 2: Check and commit.**

```bash
scripts/check
git add README.md
git commit -m "docs: multi-part plans"
```

## For the human after merge

- Run `/factory-update` here.
- Add the `factory` label to the Phase 5b issue.
