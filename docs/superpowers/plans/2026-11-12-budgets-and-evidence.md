# Budgets and Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `factory/bin/job` enforces per-job cost and time budgets and a daily spend cap, keeps an append-only spend log per job, and writes an evidence report into every PR it sends to the approver or to a human.

**Architecture:** All policy lives in `vendor/factory/factory/bin/job` (the only writer of job state). `save()` appends to `factory/jobs/<id>/log.jsonl`; `advance()` checks budgets before budgeted moves and either refuses (daily cap) or diverts the job to `needs-human` (job cap); `publish_evidence()` writes `evidence.md` and replaces the PR body. The orchestrator skill, summary, dashboard and `doctor` learn the new outputs.

**Tech Stack:** Python 3.11 stdlib, `unittest`, the existing `tests/factory_project.py` fakes.

Spec: `docs/superpowers/specs/2026-11-12-budgets-and-evidence-design.md`.
Run everything from `/Users/nandanthakur/projects/superpowers-factory`. Every
commit message ends with a blank line and the `Co-Authored-By` trailer you
were given. Vendored files change in their own commits (AGENTS.md).

`J` below means `vendor/factory/factory/bin/job`.

---

## File structure

| File | Change |
|---|---|
| `vendor/factory/factory/config.json` | add `budgets` |
| `vendor/factory/factory/bin/job` | budgets, log, enforcement, evidence, summary |
| `vendor/factory/factory/bin/doctor` | validate `budgets` |
| `vendor/factory/factory/dashboard.html` | cost shows `/ $job_usd` |
| `vendor/factory/.claude/skills/factory/SKILL.md` | `BUDGET:` lines and daily-budget waits |
| `tests/test_budgets.py` (create) | budget, log and queue tests |
| `tests/test_evidence.py` (create) | evidence tests |
| `tests/test_doctor.py` | budgets validation test |

Shared test scaffolding (used by both new test files) goes in
`tests/budget_case.py` (create), so neither file repeats it.

---

### Task 1: Config, validation and the spend log

**Files:**
- Modify: `vendor/factory/factory/config.json`
- Modify: `J` (imports, new Budgets section, `save`, `main`)
- Create: `tests/budget_case.py`, `tests/test_budgets.py`

- [ ] **Step 1: Write the shared test case**

Create `tests/budget_case.py`:

```python
"""A FactoryProject job with cost and GitHub faked, for budget and evidence tests."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from factory_project import FactoryProject

AGENTS = {
    "spec-writer": {"model": "opus", "effort": "high"},
    "builder": {"model": "opus", "effort": "high"},
    "approver": {"model": "opus", "effort": "high"},
    "reviewers": {"code": {"model": "haiku", "effort": "medium"}},
}


class BudgetCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.environ["CLAUDE_CONFIG_DIR"] = tmp.name
        self.addCleanup(os.environ.pop, "CLAUDE_CONFIG_DIR", None)
        self.project = FactoryProject(tmp.name)
        self.project.set_issue("Build the widget.", labels=("factory",))
        self.job = self.project.load_job()
        self.cost = 0.0
        self.job.cost_usd = lambda job: self.cost
        self.issues = []
        self.job.gh_json = self.fake_gh_json
        self.job_id = self.project.create_job(self.job)
        self.d = self.job.job_dir(self.job_id)

    def fake_gh_json(self, *args):
        if args[:2] == ("pr", "view"):
            return {"state": "OPEN", "isDraft": False}
        if args[:2] == ("issue", "list"):
            return list(self.issues)
        raise AssertionError(f"unexpected gh_json{args}")

    def current(self):
        return self.job.sync(self.job.load(self.job_id))

    def in_review(self, **fields):
        """The job in review, round 1 of 3, with a PR and a passing code review."""
        job = self.job.load(self.job_id)
        job.update({"stage": "review", "round": 1, "round_limit": 3, "pr": 12,
                    "pr_url": "https://github.com/o/r/pull/12", "agents": AGENTS, **fields})
        self.job.save(job)
        rd = self.d / "round-1"
        rd.mkdir(exist_ok=True)
        (rd / "review-code.md").write_text("VERDICT: PASS\n")
        Path(job["worktree"]).mkdir(parents=True, exist_ok=True)

    def advance(self, stage):
        job = self.job.advance(self.current(), stage)
        self.job.save(job)
        return job

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.main(list(argv))
        return out.getvalue()

    def gh_calls(self, *prefix):
        return [c for c in self.project.gh_calls if c[:len(prefix)] == prefix]

    def spend_elsewhere(self, usd, hours_ago=1):
        """Log spend for another job, `hours_ago` hours ago."""
        other = self.job.JOBS / "099-other"
        other.mkdir(parents=True, exist_ok=True)
        t = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with (other / "log.jsonl").open("a") as f:
            f.write(json.dumps({"t": t, "event": "sync", "stage": "review", "round": 1,
                                "cost_usd": usd, "delta_usd": usd}) + "\n")

    def log(self):
        return [json.loads(line) for line in (self.d / "log.jsonl").read_text().splitlines()]
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_budgets.py`:

```python
import unittest

from budget_case import BudgetCase


class LogTest(BudgetCase):
    def test_log_records_only_stage_or_cost_changes(self):
        self.cost = 1.5
        job = self.current()
        self.job.save(job)
        self.job.save(job)
        self.cost = 2.0
        self.job.save(self.current())
        lines = self.log()
        self.assertEqual(len(lines), 3)  # create, 1.5, 2.0
        self.assertAlmostEqual(sum(e["delta_usd"] for e in lines), 2.0)
        self.assertEqual(lines[-1]["cost_usd"], 2.0)
        self.assertEqual(set(lines[-1]), {"t", "event", "stage", "round", "cost_usd", "delta_usd"})

    def test_stage_change_logged_without_cost_change(self):
        job = self.current()
        job["stage"] = "spec"
        self.job.save(job)
        self.assertEqual([e["stage"] for e in self.log()], ["intake", "spec"])

    def test_daily_spend_counts_last_24_hours(self):
        self.spend_elsewhere(10.0, hours_ago=1)
        self.spend_elsewhere(50.0, hours_ago=30)
        self.assertAlmostEqual(self.job.daily_spend(), 10.0)

    def test_bad_log_line_dies(self):
        with (self.d / "log.jsonl").open("a") as f:
            f.write("not json\n")
        with self.assertRaises(SystemExit):
            self.job.daily_spend()


class BudgetConfigTest(BudgetCase):
    def test_invalid_value_dies(self):
        self.job.CONFIG["budgets"]["job_usd"] = "lots"
        with self.assertRaises(SystemExit):
            self.job.budgets()

    def test_missing_budgets_dies(self):
        del self.job.CONFIG["budgets"]
        with self.assertRaises(SystemExit):
            self.job.budgets()

    def test_null_and_numbers_accepted(self):
        self.job.CONFIG["budgets"].update(job_usd=None, job_hours=0.5, daily_usd=100)
        self.assertEqual(self.job.budgets()["job_hours"], 0.5)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run them to verify they fail**

Run: `python3 -m unittest discover -s tests -p 'test_budgets.py' -v`
Expected: errors (`KeyError: 'budgets'`, no `log.jsonl`, no `daily_spend`/`budgets` attribute).

- [ ] **Step 4: Implement**

In `vendor/factory/factory/config.json`, add after `"max_rounds": 3,`:

```json
  "budgets": { "job_usd": 25, "job_hours": 6, "daily_usd": 100 },
```

In `J`:

1. Change `from datetime import datetime, timezone` to
   `from datetime import datetime, timedelta, timezone`.

2. After `section()` (end of the "Job files" helpers), add:

```python
# ---- Budgets and the spend log ---------------------------------------------

BUDGET_KEYS = ("job_usd", "job_hours", "daily_usd")
EVENT = "job"  # the subcommand being run, recorded in each log line


def budgets():
    """config.json `budgets`, validated: each value a positive number or null."""
    b = CONFIG.get("budgets")
    if not isinstance(b, dict):
        die("factory/config.json has no budgets object (job_usd, job_hours, daily_usd)")
    for key in BUDGET_KEYS:
        v = b.get(key, "missing")
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0):
            die(f"factory/config.json budgets.{key} must be a positive number or null, not {v!r}")
    return b


def parse_time(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def read_log(path):
    if not path.exists():
        return []
    entries = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except ValueError:
            die(f"{path}: line {n} is not JSON")
    return entries


def append_log(job):
    """One line per change of stage or cost; delta_usd is the cost added since the last line."""
    path = job_dir(job["id"]) / "log.jsonl"
    entries = read_log(path)
    last = entries[-1] if entries else None
    cost = round(job["cost_usd"], 6)
    if last and last["stage"] == job["stage"] and last["cost_usd"] == cost:
        return
    entry = {"t": now(), "event": EVENT, "stage": job["stage"], "round": job["round"],
             "cost_usd": cost, "delta_usd": round(cost - (last["cost_usd"] if last else 0.0), 6)}
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def daily_spend():
    """Cost added by every job in the last 24 hours, from their logs."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    total = 0.0
    if JOBS.exists():
        for path in sorted(JOBS.glob("*/log.jsonl")):
            total += sum(e["delta_usd"] for e in read_log(path) if parse_time(e["t"]) >= cutoff)
    return total
```

3. In `save(job)`, after `tmp.replace(path)`, add `append_log(job)`.

4. In `main(argv)`, after the `-h/--help` block, add:

```python
    global EVENT
    cmd, args = argv[0], argv[1:]
    EVENT = cmd
    budgets()
```

   and delete the existing `cmd, args = argv[0], argv[1:]` line below it.

- [ ] **Step 5: Run the tests to verify they pass, then the whole suite**

Run: `python3 -m unittest discover -s tests -p 'test_budgets.py' -v`
Expected: 7 tests, OK.

Run: `python3 -m unittest discover -s tests -q`
Expected: OK (existing tests now also write `log.jsonl`; nothing else changes).

- [ ] **Step 6: Commit**

```bash
git add vendor/factory/factory/config.json vendor/factory/factory/bin/job tests/budget_case.py tests/test_budgets.py
git commit -m "feat: factory budgets config and per-job spend log"
```

---

### Task 2: Enforcement

**Files:**
- Modify: `J` (Budgets section, `advance`, `cmd_queue`, `main`)
- Modify: `tests/test_budgets.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_budgets.py`, before the `if __name__` line:

```python
class EnforcementTest(BudgetCase):
    def test_over_job_cost_escalates_instead_of_advancing(self):
        self.in_review()
        self.cost = 30.0
        job = self.advance("approve")
        self.assertEqual(job["stage"], "needs-human")
        decision = (self.d / "decision.md").read_text()
        self.assertTrue(decision.startswith("ESCALATE"))
        self.assertIn("budget: $30.00 of $25.00 used", decision)
        bodies = [c[-1] for c in self.gh_calls("pr", "comment")]
        self.assertTrue(any("budget: $30.00 of $25.00 used" in b for b in bodies))

    def test_over_job_time_escalates(self):
        self.in_review(started="2026-01-01T00:00:00Z")
        job = self.advance("approve")
        self.assertEqual(job["stage"], "needs-human")
        self.assertIn("h of 6 h used", (self.d / "decision.md").read_text())

    def test_advance_command_prints_budget_line(self):
        self.in_review()
        self.cost = 30.0
        out = self.run_main("advance", self.job_id, "approve")
        self.assertIn(f"BUDGET: {self.job_id} → needs-human (budget: $30.00 of $25.00 used)", out)

    def test_null_limit_disables_it(self):
        self.job.CONFIG["budgets"]["job_usd"] = None
        self.in_review()
        self.cost = 30.0
        self.assertEqual(self.advance("approve")["stage"], "approve")

    def test_feedback_gives_fresh_allowance(self):
        self.in_review()
        self.cost = 30.0
        self.advance("approve")
        self.job.cmd_feedback(self.job.load(self.job_id), "carry on")
        job = self.current()
        self.assertEqual(job["stage"], "build")
        self.assertEqual(job["budget_base_usd"], 30.0)
        self.assertIsNone(self.job.budget_problem(job))
        self.assertNotIn("budget_stopped", job)

    def test_daily_cap_refuses_and_keeps_stage(self):
        self.in_review()
        self.spend_elsewhere(150.0)
        with self.assertRaises(self.job.Refused) as cm:
            self.job.advance(self.current(), "approve")
        self.assertIn("daily budget: $150.00 of $100.00 in the last 24 h", str(cm.exception))
        self.assertEqual(self.job.load(self.job_id)["stage"], "review")

    def test_spend_older_than_a_day_does_not_count(self):
        self.in_review()
        self.spend_elsewhere(150.0, hours_ago=30)
        self.assertEqual(self.advance("approve")["stage"], "approve")

    def test_queue_waits_when_daily_cap_reached(self):
        self.in_review()
        self.issues = [{"number": 7, "title": "Build the widget"}, {"number": 8, "title": "Other"}]
        self.spend_elsewhere(150.0)
        out = self.run_main("queue")
        rows = [line.split("\t") for line in out.splitlines()]
        actions = {row[1]: (row[0], row[4]) for row in rows}
        self.assertEqual(actions["7"][0], "wait")
        self.assertEqual(actions["8"][0], "wait")
        self.assertIn("daily budget", actions["8"][1])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest discover -s tests -p 'test_budgets.py' -v`
Expected: the 8 new tests fail or error; the Task 1 tests pass.

- [ ] **Step 3: Implement**

In `J`, add at the end of the Budgets section:

```python
BUDGET_HINT = ("\n\nRaise budgets.job_usd / budgets.job_hours in factory/config.json, "
               "or give feedback to continue with a fresh allowance.")


def daily_problem():
    cap = budgets()["daily_usd"]
    spent = daily_spend()
    if cap is not None and spent >= cap:
        return f"daily budget: ${spent:.2f} of ${cap:.2f} in the last 24 h"
    return None


def budget_problem(job):
    """Why the job is over its own budget since its last allowance, or None."""
    b = budgets()
    spent = job["cost_usd"] - job.get("budget_base_usd", 0.0)
    if b["job_usd"] is not None and spent > b["job_usd"]:
        return f"budget: ${spent:.2f} of ${b['job_usd']:.2f} used"
    since = parse_time(job.get("budget_base_time") or job["started"])
    hours = (datetime.now(timezone.utc) - since).total_seconds() / 3600
    if b["job_hours"] is not None and hours > b["job_hours"]:
        return f"budget: {hours:.1f} h of {b['job_hours']:g} h used"
    return None


def budgeted_move(old, stage):
    return stage in {"gate", "review", "approve"} or (stage == "build" and old in {"gate", "review"})
```

Refactor the needs-human side effects out of `advance`. Replace this block at
the end of `advance`:

```python
    if stage == "needs-human":
        body = f"### Factory: needs a human\n\n{(d / 'decision.md').read_text().split(chr(10), 1)[1].strip()}"
        if job["pr"]:
            if gh_json("pr", "view", str(job["pr"]), "--json", "isDraft")["isDraft"]:
                gh("pr", "ready", str(job["pr"]))
            comment("pr", job["pr"], body)
        else:
            comment("issue", job["issue"], body)
        label("issue", job["issue"], add=LABELS["needs_human"])
```

with

```python
    if stage == "needs-human":
        notify_needs_human(job)
```

and add, just above `def advance`:

```python
def notify_needs_human(job):
    """Post decision.md's reason where the human will look, and label the issue."""
    d = job_dir(job["id"])
    body = f"### Factory: needs a human\n\n{(d / 'decision.md').read_text().split(chr(10), 1)[1].strip()}"
    if job["pr"]:
        if gh_json("pr", "view", str(job["pr"]), "--json", "isDraft")["isDraft"]:
            gh("pr", "ready", str(job["pr"]))
        comment("pr", job["pr"], body)
    else:
        comment("issue", job["issue"], body)
    label("issue", job["issue"], add=LABELS["needs_human"])


def stop_for_budget(job, reason):
    """Send the job to needs-human instead of the move it asked for."""
    escalate(job, reason + BUDGET_HINT)
    job["budget_stopped"] = reason
    notify_needs_human(job)
    job["stage"] = "needs-human"
    job["ended"] = now()
    return job
```

In `advance`, directly after the `require(stage in TRANSITIONS…)` line, add:

```python
    if budgeted_move(old, stage):
        daily = daily_problem()
        require(daily is None, f"{daily}; the job resumes when it drops")
        problem = budget_problem(job)
        if problem:
            return stop_for_budget(job, problem)
```

In `advance`'s `elif old == "needs-human":` branch, after
`job["round_limit"] = job["round"] + CONFIG["max_rounds"]`, add:

```python
        job["budget_base_usd"] = job["cost_usd"]
        job["budget_base_time"] = now()
        job.pop("budget_stopped", None)
```

In `cmd_queue`, at the top add `daily = daily_problem()`, and replace the
final loop

```python
    for row in rows + other_rows:
        print("\t".join(str(c) for c in row))
```

with

```python
    if daily:
        rows = [("wait",) + row[1:4] + (daily,) if row[0] in {"resume", "new"} else row for row in rows]
    for row in rows + other_rows:
        print("\t".join(str(c) for c in row))
```

In `main`, replace the `advance` branch's print:

```python
            print(f"{job['id']}: {job['stage']} (round {job['round']})")
```

with

```python
            if job["stage"] != args[1] and job.get("budget_stopped"):
                print(f"BUDGET: {job['id']} → needs-human ({job['budget_stopped']})")
            else:
                print(f"{job['id']}: {job['stage']} (round {job['round']})")
```

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `python3 -m unittest discover -s tests -p 'test_budgets.py' -v`
Expected: 15 tests, OK.

Run: `python3 -m unittest discover -s tests -q`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add vendor/factory/factory/bin/job tests/test_budgets.py
git commit -m "feat: enforce factory job and daily budgets in bin/job"
```

---

### Task 3: Evidence

**Files:**
- Modify: `J` (new Evidence section, `advance`, `stop_for_budget`, docstring, `main`)
- Create: `tests/test_evidence.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_evidence.py`:

```python
import unittest

from budget_case import BudgetCase

HEADINGS = ("### Files changed", "### Checks", "### Acceptance criteria",
            "### Plan tasks and deviations", "### Reviews", "### Budget")

BUILD_MD = """STATUS: READY

## Summary
- spins

## Acceptance criteria
1. [x] spins: test_spin passes

## Plan tasks
- [x] Task 1: Spin

## Deviations
None.
"""


class EvidenceTest(BudgetCase):
    def test_full_job_has_every_section(self):
        self.in_review(planned=True)
        (self.d / "build.md").write_text(BUILD_MD)
        (self.d / "round-1" / "checks.md").write_text("GATE: PASS\nCOMMIT: abc\n\nok 1\nok 2\n")
        text = self.job.evidence_md(self.current())
        self.assertTrue(text.startswith("<!-- factory evidence -->\n"))
        for heading in HEADINGS:
            self.assertIn(heading, text)
        self.assertIn("GATE: PASS", text)
        self.assertIn("ok 2", text)
        self.assertIn("1. [x] spins: test_spin passes", text)
        self.assertIn("- [x] Task 1: Spin", text)
        self.assertIn("- code — PASS", text)
        self.assertIn("Rounds 1 of 3", text)
        self.assertIn("of $25.00", text)
        self.assertIn("Closes #7", text)

    def test_missing_files_give_explicit_lines(self):
        text = self.job.evidence_md(self.current())
        self.assertIn("### Files changed\nnone", text)
        self.assertIn("### Checks\nnot run", text)
        self.assertIn("### Acceptance criteria\nnone recorded", text)
        self.assertIn("### Plan tasks and deviations\nnot a planned job", text)
        self.assertIn("### Reviews\nnone", text)

    def test_no_limits_say_so(self):
        self.job.CONFIG["budgets"].update(job_usd=None, job_hours=None)
        text = self.job.evidence_md(self.current())
        self.assertIn("of no limit", text)

    def test_entering_approve_replaces_pr_body(self):
        self.in_review()
        self.advance("approve")
        edits = self.gh_calls("pr", "edit", "12")
        self.assertEqual(len(edits), 1)
        self.assertIn("--body-file", edits[0])
        self.assertTrue((self.d / "evidence.md").exists())

    def test_budget_stop_publishes_evidence(self):
        self.in_review()
        self.cost = 30.0
        self.advance("approve")
        self.assertEqual(len(self.gh_calls("pr", "edit", "12")), 1)

    def test_evidence_command_without_pr_writes_file_only(self):
        out = self.run_main("evidence", self.job_id)
        self.assertTrue((self.d / "evidence.md").exists())
        self.assertEqual(self.gh_calls("pr", "edit"), [])
        self.assertIn("evidence.md", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest discover -s tests -p 'test_evidence.py' -v`
Expected: errors (`evidence_md` doesn't exist; no `pr edit` calls).

- [ ] **Step 3: Implement**

In `J`, add after the Budgets section:

```python
# ---- Evidence --------------------------------------------------------------

EVIDENCE_TAIL = 15


def evidence_md(job):
    """The PR body: why the factory thinks this job is done, or why it stopped."""
    d = job_dir(job["id"])
    b = budgets()
    build = d / "build.md"

    def build_section(heading):
        return (section(build, heading) if build.exists() else None) or "none recorded"

    files = ""
    if Path(job["worktree"]).is_dir():
        files = git(job, "diff", "--stat", f"origin/{BASE}...HEAD", check=False).stdout.strip()
    checks = "not run"
    if job["round"] and (round_dir(job) / "checks.md").exists():
        lines = (round_dir(job) / "checks.md").read_text().splitlines()
        checks = "\n".join([lines[0] if lines else "", "", "```", *lines[-EVIDENCE_TAIL:], "```"])
    planned = (f"{build_section('Plan tasks')}\n\nDeviations:\n{build_section('Deviations')}"
               if job.get("planned") else "not a planned job")
    reviews = "\n".join(f"- {r} — {v}" for r, v in sorted((job.get("reviews") or {}).items()))
    hours = (datetime.now(timezone.utc) - parse_time(job["started"])).total_seconds() / 3600
    usd_limit = f"${b['job_usd']:.2f}" if b["job_usd"] is not None else "no limit"
    hours_limit = f"{b['job_hours']:g} h" if b["job_hours"] is not None else "no limit"
    return "\n".join([
        "<!-- factory evidence -->",
        f"## Factory evidence — {job['id']}, round {job['round']}",
        "", "### Files changed", files or "none",
        "", "### Checks", checks,
        "", "### Acceptance criteria", build_section("Acceptance criteria"),
        "", "### Plan tasks and deviations", planned,
        "", "### Reviews", reviews or "none",
        "", "### Budget",
        f"Rounds {job['round']} of {job['round_limit']} · cost ${job['cost_usd']:.2f} of {usd_limit}"
        f" · time {hours:.1f} h of {hours_limit}",
        "", f"Closes #{job['issue']}", "",
    ])


def publish_evidence(job):
    """Write evidence.md and, if the job has a PR, make it the PR body."""
    path = job_dir(job["id"]) / "evidence.md"
    path.write_text(evidence_md(job))
    if job["pr"]:
        gh("pr", "edit", str(job["pr"]), "--body-file", str(path))
    return path
```

`evidence_md` copies agent-written text verbatim and never interprets it.

In `stop_for_budget`, before `return job`, add:

```python
    if job["pr"]:
        publish_evidence(job)
```

In `advance`, just before its final `return job`, add:

```python
    if stage in {"approve", "needs-human"} and job["pr"]:
        publish_evidence(job)
```

Add to the module docstring's Usage list, after the `job sync` line:

```
  job evidence <job>             write evidence.md; make it the PR body if there is a PR
```

In `main`, before the `elif cmd == "summary":` branch, add:

```python
        elif cmd == "evidence" and len(args) == 1:
            print(publish_evidence(sync(resolve(args[0]))))
```

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `python3 -m unittest discover -s tests -p 'test_evidence.py' -v`
Expected: 6 tests, OK.

Run: `python3 -m unittest discover -s tests -q`
Expected: OK. (Existing tests that move a job with a PR into `approve` or
`needs-human` now also record a `pr edit` call on the fake `gh`; none of them
asserts the absence of such calls.)

- [ ] **Step 5: Commit**

```bash
git add vendor/factory/factory/bin/job tests/test_evidence.py
git commit -m "feat: factory writes an evidence report into the PR body"
```

---

### Task 4: Summary, dashboard, orchestrator, doctor

**Files:**
- Modify: `J` (`sync`, `cmd_summary`)
- Modify: `vendor/factory/factory/dashboard.html`
- Modify: `vendor/factory/.claude/skills/factory/SKILL.md`
- Modify: `vendor/factory/factory/bin/doctor`
- Modify: `tests/test_budgets.py`, `tests/test_doctor.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_budgets.py`, before `if __name__`:

```python
class SummaryTest(BudgetCase):
    def test_summary_shows_cost_against_limit(self):
        self.cost = 3.0
        self.assertIn("$3.00/$25.00", self.run_main("summary"))

    def test_sync_records_limit_for_dashboard(self):
        self.assertEqual(self.current()["job_usd"], 25)
```

Add to `DoctorTest` in `tests/test_doctor.py`:

```python
    def test_invalid_budget_fails(self):
        def change(text):
            cfg = json.loads(text)
            cfg["budgets"]["daily_usd"] = -1
            return json.dumps(cfg)
        self.edit("factory/config.json", change)
        self.assertFails("config", "budgets.daily_usd must be a positive number or null")

    def test_missing_budgets_fails(self):
        def change(text):
            cfg = json.loads(text)
            del cfg["budgets"]
            return json.dumps(cfg)
        self.edit("factory/config.json", change)
        self.assertFails("config", "budgets missing")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest discover -s tests -p 'test_budgets.py' -v; python3 -m unittest discover -s tests -p 'test_doctor.py' -v`
Expected: the 4 new tests fail.

- [ ] **Step 3: Implement**

In `J`'s `sync`, before `return job`, add `job["job_usd"] = budgets()["job_usd"]`.

In `cmd_summary`, replace `f"${j['cost_usd']:.2f}"` in the row with
`cost_cell(j)`, and add above `cmd_summary`:

```python
def cost_cell(job):
    limit = budgets()["job_usd"]
    return f"${job['cost_usd']:.2f}/${limit:.2f}" if limit is not None else f"${job['cost_usd']:.2f}"
```

In `vendor/factory/factory/dashboard.html`, replace

```js
    `<span>$${Number(job.cost_usd).toFixed(2)}</span>`,
```

with

```js
    `<span>$${Number(job.cost_usd).toFixed(2)}${job.job_usd ? ` / $${Number(job.job_usd).toFixed(2)}` : ''}</span>`,
```

In `vendor/factory/.claude/skills/factory/SKILL.md`:

1. Insert this paragraph immediately before the line that starts
   `A person can merge a job's PR by hand at any stage.`:

   ```markdown
   **Budgets.** `factory/bin/job advance` may print
   `BUDGET: <id> → needs-human (<reason>)` instead of the move you asked for:
   the job went over `budgets.job_usd` or `budgets.job_hours` and is finished
   for this run. Report the line. If it refuses with `daily budget: …`, the
   factory has spent `budgets.daily_usd` in the last 24 h: start nothing else,
   let running agents finish, then end the run with the summary.
   ```

2. In `## /factory run` step 1, after the sentence ending
   `fix it and run again.`, add:
   `` `wait` lines whose note starts with `daily budget` mean the daily cap is reached: start nothing. ``

In `vendor/factory/factory/bin/doctor`'s `check_config`, before `return problems`, add:

```python
    budget = cfg.get("budgets")
    if not isinstance(budget, dict):
        problems.append(fail("budgets missing; expected job_usd, job_hours and daily_usd"))
    else:
        for key in ("job_usd", "job_hours", "daily_usd"):
            v = budget.get(key, "missing")
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0):
                problems.append(fail(f"budgets.{key} must be a positive number or null, not {v!r}"))
```

- [ ] **Step 4: Run every test and the repo check**

Run: `python3 -m unittest discover -s tests -q && scripts/check`
Expected: OK; seven `PASS` lines, exit 0.

- [ ] **Step 5: Commit**

```bash
git add vendor/factory/factory/bin/job vendor/factory/factory/bin/doctor vendor/factory/factory/dashboard.html vendor/factory/.claude/skills/factory/SKILL.md tests/test_budgets.py tests/test_doctor.py
git commit -m "feat: budgets in summary, dashboard, orchestrator and doctor"
```
