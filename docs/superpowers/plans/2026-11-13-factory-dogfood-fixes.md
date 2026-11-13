# Factory Dogfood Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the seven problems found when the factory built Phase 1 on its own repo.

**Architecture:**
- **Vendored source:** small edits in `vendor/factory/` to `factory/bin/job`, `factory/bin/gate`, the builder prompt and the factory skill. Each edit gets its own vendored-only commit, followed by a plugin-side commit with its tests and the refreshed `vendor/known-hashes.json`.
- **Plugin side:** an edit to the `factory-handoff` skill and one test fix.

**Tech Stack:** Python 3.11 stdlib, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-13-factory-dogfood-fixes-design.md`

**Rules for this plan:**
- Never edit the spec or this plan.
- Make no git tags.
- Push nothing but the job branch.
- After every vendored edit, run `scripts/known-hashes` and commit `vendor/known-hashes.json` with the tests.
- Full check: `scripts/check`.
- One test file: `python3 -m unittest tests/<file>.py -v` from the repo root.

---

### Task 1: `job planned` records the pinned spec and plan paths

**Files:**
- Modify: `vendor/factory/factory/bin/job` (`cmd_planned`, the line `job = {**sync(job), "planned": True, "agents": ...}`)
- Test: `tests/test_job_planned.py` (`PlannedSuccessTest`)

- [ ] **Step 1: Write the failing test.** Add to `PlannedSuccessTest`:

```python
    def test_planned_job_records_its_spec_and_plan_paths(self):
        self.job.cmd_planned(self.load())
        self.assertEqual(self.load()["plan_paths"],
                         ["docs/superpowers/specs/2026-11-12-widget-design.md",
                          "docs/superpowers/plans/2026-11-12-widget.md"])
```

- [ ] **Step 2: Run it and see it fail.** `python3 -m unittest tests/test_job_planned.py -v` should fail with a `KeyError` on `plan_paths`.

- [ ] **Step 3: Implement.** In `cmd_planned`, change

```python
    job = {**sync(job), "planned": True, "agents": route_agents(plan["risk"], plan["surfaces"])}
```

to

```python
    job = {**sync(job), "planned": True, "plan_paths": [plan["spec"], plan["plan"]],
           "agents": route_agents(plan["risk"], plan["surfaces"])}
```

- [ ] **Step 4: Run the tests.** `python3 -m unittest tests/test_job_planned.py -v` should pass.

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/factory/bin/job
git commit -m "fix(vendor): planned jobs record their spec and plan paths"
scripts/known-hashes
git add tests/test_job_planned.py vendor/known-hashes.json
git commit -m "test: planned jobs record plan paths; refresh known hashes"
```

---

### Task 2: The gate protects a planned job's spec and plan

**Files:**
- Modify: `vendor/factory/factory/bin/gate` (`protected_changes`, `gate`)
- Test: `tests/test_gate_plan_paths.py` (new)

- [ ] **Step 1: Write the failing tests.** Create `tests/test_gate_plan_paths.py`:

```python
import importlib.machinery
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_project import FactoryProject, git  # noqa: E402

VENDOR_GATE = Path(__file__).resolve().parents[1] / "vendor/factory/factory/bin/gate"
SPEC = "docs/superpowers/specs/2026-11-12-widget-design.md"
PLAN = "docs/superpowers/plans/2026-11-12-widget.md"


class GatePlanPathsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        target = self.project.repo / "factory/bin/gate"
        target.write_bytes(VENDOR_GATE.read_bytes())
        loader = importlib.machinery.SourceFileLoader(f"gate_{id(self)}", str(target))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.gate = importlib.util.module_from_spec(spec)
        loader.exec_module(self.gate)
        self.wt = Path(tmp.name) / "wt"
        git(self.project.repo, "worktree", "add", "-q", "-b", "job", str(self.wt), "origin/main")

    def commit(self, rel, text):
        (self.wt / rel).write_text(text)
        git(self.wt, "add", rel)
        git(self.wt, "-c", "user.email=t@example.com", "-c", "user.name=T", "commit", "-q", "-m", "x")

    def test_planned_job_patterns_include_its_spec_and_plan(self):
        patterns = self.gate.protected_patterns({"plan_paths": [SPEC, PLAN]})
        self.assertIn(SPEC, patterns)
        self.assertIn(PLAN, patterns)
        self.assertIn("factory/checks.sh", patterns)

    def test_unplanned_job_patterns_are_the_config_ones(self):
        self.assertEqual(self.gate.protected_patterns({}), self.gate.CONFIG["protected_paths"])

    def test_editing_the_plan_is_a_protected_change(self):
        self.commit(PLAN, "# rewritten\n")
        hits = self.gate.protected_changes(str(self.wt), self.gate.protected_patterns({"plan_paths": [SPEC, PLAN]}))
        self.assertEqual(hits, [f"M {PLAN}"])

    def test_editing_the_plan_is_fine_for_an_unplanned_job(self):
        self.commit(PLAN, "# rewritten\n")
        self.assertEqual(self.gate.protected_changes(str(self.wt), self.gate.protected_patterns({})), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them and see them fail.** `python3 -m unittest tests/test_gate_plan_paths.py -v` should fail with an `AttributeError` for `protected_patterns`.

- [ ] **Step 3: Implement.** In `vendor/factory/factory/bin/gate`, replace `protected_changes` with:

```python
def protected_patterns(job):
    """config.json protected_paths, plus a planned job's own spec and plan, which are fixed."""
    return CONFIG["protected_paths"] + list(job.get("plan_paths") or [])


def protected_changes(worktree, patterns):
    """Existing files matching `patterns` that the branch modified or deleted."""
    diff = git(worktree, "diff", "--name-status", f"origin/{CONFIG['base_branch']}...HEAD")
    hits = []
    for line in diff.splitlines():
        status, *paths = line.split("\t")
        if status.startswith("A"):
            continue
        old = paths[0]  # for renames and copies, the original path
        if any(fnmatch.fnmatch(old, pattern) for pattern in patterns):
            hits.append(f"{status[0]} {old}")
    return hits
```

In `gate()`, change `protected = protected_changes(worktree)` to `protected = protected_changes(worktree, protected_patterns(job))`. Then extend the module docstring sentence about `protected_paths` with: "For a planned job it also fails when the branch modifies the spec or plan the job was planned from (`plan_paths` in job.json)."

- [ ] **Step 4: Run the tests.** `python3 -m unittest tests/test_gate_plan_paths.py tests/test_gate_env.py -v` should pass.

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/factory/bin/gate
git commit -m "fix(vendor): gate protects a planned job's spec and plan"
scripts/known-hashes
git add tests/test_gate_plan_paths.py vendor/known-hashes.json
git commit -m "test: gate protects plan paths; refresh known hashes"
```

---

### Task 3: Cost by model

**Files:**
- Modify: `vendor/factory/factory/bin/job` (`cost_for_needle`, the Budget line of `evidence_md`, `main`, the module docstring's command list)
- Test: `tests/test_cost_by_model.py` (new)

- [ ] **Step 1: Write the failing tests.** Create `tests/test_cost_by_model.py`:

```python
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_project import FactoryProject  # noqa: E402


class CostByModelTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.project = FactoryProject(tmp.name)
        self.job = self.project.load_job()
        self.needle = "Job folder: /x/factory/jobs/001-a/"

    def transcript(self, name, model, input_tokens):
        sub = self.job.transcripts_dir() / "s1" / "subagents"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / f"agent-{name}.jsonl").write_text(
            json.dumps({"message": {"content": f"{self.needle} go"}}) + "\n"
            + json.dumps({"type": "assistant", "message": {
                "id": f"m-{name}", "model": model, "usage": {"input_tokens": input_tokens, "output_tokens": 0}}})
            + "\n")

    def test_split_by_model_and_total_matches(self):
        self.transcript("a", "claude-opus-5-5", 1_000_000)     # $4.00
        self.transcript("b", "claude-sonnet-5-5", 500_000)     # $1.00
        self.transcript("c", "claude-opus-5-5", 250_000)       # $1.00
        by = self.job.cost_by_model(self.needle)
        self.assertEqual(by, {"claude-opus-5-5": 5.0, "claude-sonnet-5-5": 1.0})
        self.assertEqual(self.job.cost_for_needle(self.needle), 6.0)

    def test_other_jobs_do_not_count(self):
        self.transcript("a", "claude-opus-5-5", 1_000_000)
        self.assertEqual(self.job.cost_by_model("Job folder: /x/factory/jobs/002-b/"), {})

    def test_model_summary_is_largest_first_without_prefix(self):
        self.assertEqual(self.job.model_summary({"claude-sonnet-5-5": 0.6, "claude-opus-5-5": 4.97}),
                         "opus-5-5 $4.97, sonnet-5-5 $0.60")
        self.assertEqual(self.job.model_summary({}), "none")

    def test_job_costs_prints_each_model_and_the_total(self):
        self.project.set_issue("Build it.", labels=("factory",))
        job_id = self.project.create_job(self.job)
        needle = f"Job folder: {self.job.job_dir(job_id)}/"
        self.needle = needle
        self.transcript("a", "claude-opus-5-5", 1_000_000)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.main(["costs", job_id])
        self.assertEqual(out.getvalue().splitlines(), ["claude-opus-5-5  $4.00", "total $4.00"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them and see them fail.** `python3 -m unittest tests/test_cost_by_model.py -v` should fail with an `AttributeError` for `cost_by_model`.

- [ ] **Step 3: Implement.** In `vendor/factory/factory/bin/job`:

Rename the body of `cost_for_needle` into `cost_by_model`, keeping the same docstring paragraph about transcripts. Key the accumulation by model:

```python
def cost_by_model(needle):
    """{model: API-equivalent cost} of every subagent whose first prompt line contains `needle`.

    Claude Code writes each subagent's messages, with model and token usage, to
    <config>/projects/<project>/<session>/subagents/agent-<id>.jsonl. Every
    factory prompt starts with `Job folder: <path>`, which ties a transcript to
    its job across sessions.
    """
    prices = CONFIG["prices_usd_per_mtok"]
    totals = {}
    for path in transcripts_dir().glob("*/subagents/agent-*.jsonl"):
        with path.open() as f:
            first = f.readline()
            if not first or needle not in prompt_text(first):
                continue
            usage_by_message = {}
            for line in f:
                entry = json.loads(line)
                msg = entry.get("message")
                if entry.get("type") == "assistant" and isinstance(msg, dict) and msg.get("usage"):
                    usage_by_message[msg["id"]] = (msg["model"], msg["usage"])
        for model, u in usage_by_message.values():
            tokens = (u.get("input_tokens", 0) + u.get("output_tokens", 0)
                      + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0))
            if tokens == 0:
                continue
            if model not in prices:
                die(f"no price for model {model} in factory/config.json prices_usd_per_mtok")
            p = prices[model]
            split = u.get("cache_creation") or {}
            write_1h = split.get("ephemeral_1h_input_tokens", 0)
            write_5m = u.get("cache_creation_input_tokens", 0) - write_1h
            totals[model] = totals.get(model, 0.0) + (
                u.get("input_tokens", 0) * p["input"]
                + u.get("output_tokens", 0) * p["output"]
                + write_5m * p["cache_write_5m"]
                + write_1h * p["cache_write_1h"]
                + u.get("cache_read_input_tokens", 0) * p["cache_read"]) / 1e6
    return {model: round(usd, 2) for model, usd in totals.items()}


def cost_for_needle(needle):
    """API-equivalent cost of every subagent whose first prompt line contains `needle`."""
    return round(sum(cost_by_model(needle).values()), 2)


def model_summary(by_model):
    """`opus-5-5 $4.97, sonnet-5-5 $0.60`: largest first, without the `claude-` prefix."""
    if not by_model:
        return "none"
    ranked = sorted(by_model.items(), key=lambda kv: -kv[1])
    return ", ".join(f"{m.removeprefix('claude-')} ${usd:.2f}" for m, usd in ranked)


def cmd_costs(job):
    by_model = cost_by_model(f"Job folder: {job_dir(job['id'])}/")
    width = max((len(m) for m in by_model), default=0)
    for model, usd in sorted(by_model.items(), key=lambda kv: -kv[1]):
        print(f"{model.ljust(width)}  ${usd:.2f}")
    print(f"total ${sum(by_model.values()):.2f}")
```

(`cost_usd(job)` keeps calling `cost_for_needle`, so nothing else changes.) Keep the existing cost arithmetic exactly as it is today: the code above only adds the per-model key, so compare it with the current function line by line before you replace it.

In `evidence_md`, before the list that holds the `### Budget` lines, add:

```python
    by_model = model_summary(cost_by_model(f"Job folder: {job_dir(job['id'])}/"))
```

and after `f" · time {hours:.1f} h of {hours_limit} since the last allowance",` add:

```python
        f" · by model: {by_model}",
```

In `main`, next to `elif cmd == "summary":`, add:

```python
        elif cmd == "costs" and len(args) == 1:
            cmd_costs(resolve(args[0]))
```

In the module docstring's command list, add `  job costs <job>                cost of the job's agents by model`.

- [ ] **Step 4: Run the tests.** `python3 -m unittest tests/test_cost_by_model.py tests/test_budgets.py tests/test_evidence.py tests/test_learning.py -v` should pass. If an evidence test compares the exact Budget line, update its expected text to include ` · by model: none`; that's the new behaviour, not a weakened test.

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/factory/bin/job
git commit -m "feat(vendor): job costs and the evidence block show cost by model"
scripts/known-hashes
git add tests/test_cost_by_model.py tests/test_evidence.py vendor/known-hashes.json
git commit -m "test: cost by model; refresh known hashes"
```

(Stage `tests/test_evidence.py` only if you changed it.)

---

### Task 4: Builder prompt and factory skill wording

**Files:**
- Modify: `vendor/factory/.claude/agents/builder.md` (section `## Planned jobs`)
- Modify: `vendor/factory/.claude/skills/factory/SKILL.md` (header paragraph, the "Name the builder" paragraph, **build**)
- Test: `tests/test_dogfood_wording.py` (new)

- [ ] **Step 1: Write the failing tests.** Create `tests/test_dogfood_wording.py`:

```python
import unittest
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[1] / "vendor/factory"
BUILDER = (VENDOR / ".claude/agents/builder.md").read_text()
SKILL = (VENDOR / ".claude/skills/factory/SKILL.md").read_text()


class WordingTest(unittest.TestCase):
    def test_skill_no_longer_names_the_builder(self):
        self.assertNotIn("builder-<id>", SKILL)
        self.assertIn("resume it with `SendMessage` to the agent id", SKILL)

    def test_skill_says_where_base_comes_from(self):
        self.assertIn("built from `job.json` and `base_branch` in `factory/config.json`", SKILL)

    def test_builder_never_edits_the_planned_spec_or_plan(self):
        self.assertIn("Never edit the spec or plan files the job was planned from", BUILDER)

    def test_builder_skips_tags_and_lists_skipped_steps_for_the_human(self):
        self.assertIn("worktree or tag", BUILDER)
        self.assertIn("`For the human: <step>`", BUILDER)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them and see them fail.** `python3 -m unittest tests/test_dogfood_wording.py -v` should show 4 failures.

- [ ] **Step 3: Edit `builder.md`, `## Planned jobs`.** Replace

```
  its paths and skip any step that creates a branch or worktree, or that
  merges, opens a PR or pushes anything other than your job branch.
```

with

```
  its paths and skip any step that creates a branch, worktree or tag, merges,
  opens a PR, pushes anything other than your job branch, or changes files
  outside your worktree. List each skipped step under `## Deviations` as
  `For the human: <step>`.
- Never edit the spec or plan files the job was planned from (`intake.md`
  names them); the gate fails the round if you do. If a task asks you to,
  skip that step and record it under `## Deviations`.
```

- [ ] **Step 4: Edit `SKILL.md`.**
  - Replace `Every prompt starts with the job's header, built from \`job.json\`:` with `Every prompt starts with the job's header, built from \`job.json\` and \`base_branch\` in \`factory/config.json\`:`.
  - Replace the paragraph that starts `Name the builder \`builder-<id>\`.` (3 lines, ending `Start every message to it with \`<header>\` too.`) with:

```
When this session spawned the job's builder, resume it with `SendMessage` to the agent id its
spawn result gave; otherwise spawn a new `builder`. Start every message to it with `<header>` too.
```

  - In **build**, replace ``Spawn or resume `builder-<id>` with`` with `Spawn or resume the job's builder with`.
  - Search the file for any other `builder-<id>` and reword it the same way.

- [ ] **Step 5: Run the tests and the full check.** `python3 -m unittest tests/test_dogfood_wording.py -v` should pass. Then `scripts/known-hashes` and `scripts/check` should pass.

- [ ] **Step 6: Commit.**

```bash
git add vendor/factory/.claude/agents/builder.md vendor/factory/.claude/skills/factory/SKILL.md
git commit -m "fix(vendor): builder keeps planned spec and plan fixed; skill wording for resume and base"
git add tests/test_dogfood_wording.py vendor/known-hashes.json
git commit -m "test: builder and skill wording; refresh known hashes"
```

---

### Task 5: `/factory-handoff` warns about skipped steps and escalations

**Files:**
- Modify: `skills/factory-handoff/SKILL.md` (§2 and §3)
- Test: `tests/test_handoff_skill.py` (new)

- [ ] **Step 1: Write the failing tests.** Create `tests/test_handoff_skill.py`:

```python
import unittest
from pathlib import Path

SKILL = (Path(__file__).resolve().parents[1] / "skills/factory-handoff/SKILL.md").read_text()


class HandoffSkillTest(unittest.TestCase):
    def test_checks_for_steps_outside_the_job_branch(self):
        for needle in ("git tag", "--force", "git checkout", "git merge"):
            self.assertIn(needle, SKILL)
        self.assertIn("the factory will skip them", SKILL)

    def test_warns_when_the_approver_will_escalate(self):
        self.assertIn(".claude/agents/approver.md", SKILL)
        self.assertIn("will stop at needs-human for you to merge", SKILL)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them and see them fail.** `python3 -m unittest tests/test_handoff_skill.py -v` should fail.

- [ ] **Step 3: Edit §2.** Just before `Then record the commit:`, add:

````markdown
Check the plan for steps a factory job can't do: it works only on its own
branch in its own worktree.

```bash
grep -nE 'git tag|git push|--force|git checkout (main|master|"?\$BASE)|git merge' <plan>
```

If anything matches other than pushing the plan's own feature branch, show
the lines and say the factory will skip them and list them for the human
under `## Deviations`. Ask whether to file anyway or fix the plan first.
````

- [ ] **Step 4: Edit §3.** After the paragraph that ends `Don't file anything until they confirm.`, add:

```markdown
Then read the ESCALATE lists in `.claude/agents/approver.md` (the general
list and any "In this project" list). If the plan clearly changes something
on them, tell your human partner which rule, and that the approver will
escalate, so the job will stop at needs-human for you to merge. This is
information only; it doesn't stop the handoff.
```

- [ ] **Step 5: Run the tests and the check.** `python3 -m unittest tests/test_handoff_skill.py -v` should pass, then `scripts/check`.

- [ ] **Step 6: Commit.**

```bash
git add skills/factory-handoff/SKILL.md tests/test_handoff_skill.py
git commit -m "feat: factory-handoff warns about skipped steps and approver escalations"
```

---

### Task 6: The runner queue-failure test no longer sleeps

**Files:**
- Modify: `tests/test_runner.py` (`SpecGapTest.test_queue_failure_is_an_error`)

- [ ] **Step 1: Measure the current time.** `python3 -m unittest tests.test_runner.SpecGapTest.test_queue_failure_is_an_error -v` should take about 7 s.

- [ ] **Step 2: Change the test.** Replace its body with:

```python
    def test_queue_failure_is_an_error(self):
        # Unparseable output fails `job queue` without a retryable gh error, so no retry waits.
        bad = self.tmp / "bad-issues.json"
        bad.write_text("not json")
        res = self.runner("tick", FAKE_ISSUES=str(bad))
        self.assertEqual(res.returncode, 1)
        self.assertRegex(self.log_lines()[-1], r" error: queue: ")
```

(`runner_env` applies keyword overrides after its defaults, so `FAKE_ISSUES` here wins.)

- [ ] **Step 3: Run it.** The same command should pass in under 2 s.

- [ ] **Step 4: Run the full check.** `scripts/check` should pass.

- [ ] **Step 5: Commit.**

```bash
git add tests/test_runner.py
git commit -m "test: queue failure test no longer waits out network retries"
```
