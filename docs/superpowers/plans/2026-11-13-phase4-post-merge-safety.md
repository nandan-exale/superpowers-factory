# Phase 4: Safety After the Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pause and resume the queue; watch the base branch after each factory merge and, when it goes red, open a revert PR and pause; stop risky changes (dependencies, CI) at merge until a human adds `factory:risk-ok`; and scan for secrets before every push.

**Architecture:**
- **Vendored `job`:**
  - `paused.json` with `job pause` and `job resume`. The queue starts nothing while paused, and `merging` is refused.
  - `job watch` checks each merged job's base-branch runs (`gh run list --commit`) and handles a red base with `revert_for()`.
  - `cmd_merge` refuses risky changes listed in `checks.md` unless the issue has `factory:risk-ok`. A new, narrow `needs-human → merging` move lets such a job merge once the label is added.
  - `job scan` and `job push` scan the diff's added lines for secret patterns.
- **Vendored `gate`:** `## Risky changes` and `## Secrets` sections in `checks.md`. A secret fails the gate, and `advance` then sends the job to `needs-human` ("rotate it") instead of `build`.
- **Vendored builder prompt, skill, runner, doctor, dashboard and config;** plugin install and uninstall skills; test helpers; README; an e2e scenario.

**Tech Stack:** Python 3.10+ stdlib, `unittest`, `git`, the `gh` CLI (faked in tests).

**Spec:** `docs/superpowers/specs/2026-11-13-phase4-post-merge-safety-design.md`

**Rules for this plan:**
- Never edit the spec or this plan. Make no git tags. Push nothing but the job branch.
- Each vendored edit gets its own commit (`feat(vendor): …`); then a plugin-side commit with tests and the refreshed `vendor/known-hashes.json` (`scripts/known-hashes`).
- Change nothing in the installed copy (`factory/`, `.claude/` at the repo root).
- Old configs must keep working: read `watch`, `risky_paths`, `secret_scan` and the new `labels` keys with defaults. `/factory-update` adds them to installed configs.
- Tests build secret-looking strings at runtime (for example `"AKIA" + "A" * 16`), so no real-looking secret is ever committed.
- This plan is built after Phase 3 (visibility) is merged. Phase 3 added `chores()` in the runner and `factory:digest` in `LABELS`; this plan extends both. If either is missing on the base branch, add what this plan needs in the same place and note it under `## Deviations`.
- One step goes past the spec's text, because the spec's flow needs it. "Add `factory:risk-ok` and run the factory again" only works if a job stopped for risk can return from `needs-human` to `merging`. Task 3 adds that move, narrowly: only for a job with `risk_stopped`, and only once the label is on the issue.
- Full check: `scripts/check`. One test file: `python3 -m unittest tests/<file>.py -v`.

## File map

| File | Change |
|---|---|
| `vendor/factory/factory/bin/job` | pause/resume; watch and revert; risky stop and the `needs-human → merging` move; secret scan and push |
| `vendor/factory/factory/bin/gate` | `## Risky changes`, `## Secrets` |
| `vendor/factory/factory/config.json` | `watch`, `risky_paths`, `secret_scan`, `labels.revert`, `labels.risk_ok` |
| `vendor/factory/factory/bin/doctor` | labels; config validation; WARN when paused |
| `vendor/factory/factory/bin/runner` | `job watch` first in `chores()` |
| `vendor/factory/.claude/agents/builder.md` | push with `job push` |
| `vendor/factory/.claude/skills/factory/SKILL.md` | watch at start, paused queue, resume, risk-ok resume |
| `vendor/factory/factory/dashboard.html` | paused banner |
| `skills/factory-install/SKILL.md`, `skills/factory-uninstall/SKILL.md`, `tests/installed_project.py` | the two labels |
| `tests/test_pause.py`, `tests/test_risky.py`, `tests/test_secret_scan.py`, `tests/test_watch.py`, `tests/test_revert.py`, `tests/test_safety_wording.py` | new |
| `README.md`, `tests/e2e/risky-change/scenario.json`, `tests/test_e2e_scenarios.py` | docs, e2e |

---

### Task 1: Pause and resume

**Files:**
- Modify: `vendor/factory/factory/bin/job`
- Create: `tests/test_pause.py`

- [ ] **Step 1: Write the failing tests.** `tests/test_pause.py`:

```python
import contextlib
import io
import json
import unittest

from budget_case import BudgetCase


class PauseTest(BudgetCase):
    def out(self, fn, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn(*args)
        return buf.getvalue()

    def test_pause_and_resume_round_trip(self):
        self.assertIsNone(self.job.paused())
        self.assertIn("PAUSED: main is red", self.out(self.job.cmd_pause, "main is red"))
        state = json.loads((self.job.JOBS / "paused.json").read_text())
        self.assertEqual((state["reason"], state["job"], state["sha"]), ("main is red", None, None))
        self.assertIn("RESUME: cleared main is red", self.out(self.job.cmd_resume))
        self.assertIsNone(self.job.paused())
        self.assertIn("RESUME: not paused", self.out(self.job.cmd_resume))

    def test_an_unreadable_pause_file_still_pauses(self):
        self.job.JOBS.mkdir(parents=True, exist_ok=True)
        (self.job.JOBS / "paused.json").write_text("{bad")
        self.assertIn("unreadable", self.job.paused()["reason"])

    def test_queue_starts_nothing_while_paused(self):
        self.issues = [{"number": 7, "title": "Build the widget"}, {"number": 8, "title": "Another"}]
        self.job.pause("main is red")
        lines = self.out(self.job.cmd_queue).splitlines()
        self.assertTrue(lines[0].startswith("PAUSED: main is red (since "))
        self.assertFalse([l for l in lines[1:] if l.split("\t")[0] in {"resume", "new"}])
        self.assertTrue(any(l.startswith("wait\t8") and l.endswith("paused") for l in lines))

    def test_merging_is_refused_while_paused(self):
        self.in_review()
        self.advance("approve")
        (self.d / "decision.md").write_text("APPROVE\n")
        self.job.pause("main is red")
        with self.assertRaisesRegex(self.job.Refused, "the queue is paused"):
            self.advance("merging")

    def test_summary_shows_the_pause(self):
        self.job.pause("main is red")
        self.assertTrue(self.out(self.job.cmd_summary, []).startswith("PAUSED: main is red"))
```

- [ ] **Step 2: Run them and see them fail** with `AttributeError` (no `paused`).

- [ ] **Step 3: Implement.** In `vendor/factory/factory/bin/job`, after `LEARNING = JOBS / "learning"` and its constants (any place in the module scope before `advance`), add:

```python
# ---- Pause -----------------------------------------------------------------

PAUSE_FILE = JOBS / "paused.json"


def paused():
    """The pause record, or None. An unreadable file still pauses: only `job resume` clears it."""
    try:
        return json.loads(PAUSE_FILE.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"reason": "paused.json is unreadable; run factory/bin/job resume", "job": None, "sha": None,
                "time": "?"}


def pause(reason, job_id=None, sha=None):
    JOBS.mkdir(parents=True, exist_ok=True)
    tmp = JOBS / "paused.json.tmp"
    tmp.write_text(json.dumps({"reason": reason, "job": job_id, "sha": sha, "time": now()}) + "\n")
    tmp.replace(PAUSE_FILE)


def paused_line(p):
    return f"PAUSED: {p['reason']} (since {p['time']}; run factory/bin/job resume after fixing)"


def cmd_pause(reason):
    require(reason.strip(), "give a reason: factory/bin/job pause <reason>")
    pause(reason.strip())
    print(paused_line(paused()))


def cmd_resume():
    p = paused()
    if not p:
        print("RESUME: not paused")
        return
    PAUSE_FILE.unlink(missing_ok=True)
    print(f"RESUME: cleared {p['reason']} (since {p['time']})")
```

In `advance`, right after the first `require(...)` (the legal-transition check), add:

```python
    if stage == "merging":
        p = paused()
        require(not p, f"the queue is paused: {p['reason'] if p else ''}; run factory/bin/job resume first")
```

In `cmd_merge`, as its first line (before `sync(job)`), add the same guard for a job already in `merging`:

```python
    p = paused()
    require(not p, f"the queue is paused: {p['reason'] if p else ''}; run factory/bin/job resume first")
```

In `cmd_queue`, replace the block

```python
    if daily:
        rows = [("wait",) + row[1:4] + (daily,) if row[0] in {"resume", "new"} else row for row in rows]
```

with

```python
    hold = paused()
    if hold:
        print(paused_line(hold))
    why = "paused" if hold else daily
    if why:
        rows = [("wait",) + row[1:4] + (why,) if row[0] in {"resume", "new"} else row for row in rows]
```

In `cmd_summary`, as its first lines:

```python
    p = paused()
    if p:
        print(paused_line(p))
```

Usage lines (after `job costs`):

```
  job pause <reason>             stop the queue: nothing starts and nothing merges until `job resume`
  job resume                     clear the pause (a human runs this once the base branch is fixed)
```

`main`, before the final `else:`:

```python
        elif cmd == "pause" and args:
            cmd_pause(" ".join(args))
        elif cmd == "resume" and not args:
            cmd_resume()
```

- [ ] **Step 4: Run them and see them pass.** `python3 -m unittest tests/test_pause.py tests/test_budgets.py -v`. The runner needs no change: `has_work()` sees no `resume` or `new` rows while paused, so a tick logs `idle`.

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/factory/bin/job
git commit -m "feat(vendor): job pause and resume; the queue and merges stop while paused"
scripts/known-hashes
git add tests/test_pause.py vendor/known-hashes.json
git commit -m "test: pause and resume; refresh known hashes"
```

---

### Task 2: Risky changes in the gate

**Files:**
- Modify: `vendor/factory/factory/bin/gate`, `vendor/factory/factory/config.json`
- Create: `tests/test_risky.py`

- [ ] **Step 1: Write the failing tests.** `tests/test_risky.py`:

```python
import importlib.machinery
import importlib.util
import tempfile
import unittest
from pathlib import Path

from factory_project import FactoryProject, git

VENDOR_GATE = Path(__file__).resolve().parents[1] / "vendor/factory/factory/bin/gate"


class RiskyGateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        target = self.project.repo / "factory/bin/gate"
        target.write_bytes(VENDOR_GATE.read_bytes())
        loader = importlib.machinery.SourceFileLoader(f"gate_{id(self)}", str(target))
        self.gate = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(self.gate)
        self.wt = Path(tmp.name) / "wt"
        git(self.project.repo, "worktree", "add", "-q", "-b", "job", str(self.wt), "origin/main")

    def commit(self, files):
        for rel, text in files.items():
            (self.wt / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.wt / rel).write_text(text)
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "change")

    def test_path_matches_root_and_nested_double_star(self):
        m = self.gate.path_matches
        self.assertTrue(m("package.json", "**/package.json"))
        self.assertTrue(m("web/package.json", "**/package.json"))
        self.assertTrue(m(".github/workflows/ci.yml", ".github/workflows/**"))
        self.assertTrue(m("requirements-dev.txt", "**/requirements*.txt"))
        self.assertFalse(m("src/package.py", "**/package.json"))

    def test_lists_added_modified_and_deleted_risky_files(self):
        self.commit({"package.json": "{}\n", ".github/workflows/ci.yml": "on: push\n", "src/app.py": "x = 1\n"})
        hits = self.gate.risky_changes(self.wt, self.gate.CONFIG["risky_paths"])
        self.assertEqual(sorted(hits), ["A .github/workflows/ci.yml", "A package.json"])

    def test_old_config_without_risky_paths_lists_nothing(self):
        self.commit({"package.json": "{}\n"})
        self.assertEqual(self.gate.risky_changes(self.wt, self.gate.CONFIG.get("no-such-key", [])), [])
```

- [ ] **Step 2: Run them and see them fail** with `AttributeError` (no `path_matches`).

- [ ] **Step 3: Config.** In `vendor/factory/factory/config.json`, add after `protected_paths`:

```json
  "risky_paths": [".github/workflows/**", "**/package.json", "**/package-lock.json",
    "**/pnpm-lock.yaml", "**/yarn.lock", "**/pyproject.toml", "**/requirements*.txt",
    "**/poetry.lock", "**/uv.lock", "**/Cargo.toml", "**/Cargo.lock", "**/go.mod",
    "**/go.sum", "**/Gemfile", "**/Gemfile.lock", "Dockerfile", "**/*.tf"],
```

and in `labels` add `"revert": "factory:revert", "risk_ok": "factory:risk-ok"`.

- [ ] **Step 4: Gate.** In `vendor/factory/factory/bin/gate`, after `protected_changes`, add:

```python
def path_matches(path, pattern):
    """fnmatch (whose * also crosses /), plus `**/x` matching `x` at the root."""
    return fnmatch.fnmatch(path, pattern) or (pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:]))


def risky_changes(worktree, patterns):
    """Changed files (added, modified, deleted or renamed) matching config risky_paths."""
    diff = git(worktree, "diff", "--name-status", f"origin/{CONFIG['base_branch']}...HEAD")
    hits = []
    for line in diff.splitlines():
        status, *paths = line.split("\t")
        if any(path_matches(p, pattern) for p in paths for pattern in patterns):
            hits.append(f"{status[0]} {paths[-1]}")
    return hits
```

In `gate()`, after `protected = protected_changes(...)`, add:

```python
    risky = risky_changes(worktree, CONFIG.get("risky_paths", []))
```

add to `summary`, after the protected-paths bullet:

```python
        f"Risky changes: {', '.join(risky) if risky else 'none'}",
```

and in the `checks.md` text, after the `## Protected paths` section's content and before `## checks.sh`, add:

```python
        + "\n\n## Risky changes\n"
        + ("\n".join(f"- {r}" for r in risky) if risky else "None.")
```

(The verdict doesn't change: risky files are flagged, not failed.)

- [ ] **Step 5: Run them and see them pass**, then `python3 -m unittest tests/test_gate_plan_paths.py tests/test_gate_env.py -v` and `scripts/check --fast`.

- [ ] **Step 6: Commit.**

```bash
git add vendor/factory/factory/bin/gate vendor/factory/factory/config.json
git commit -m "feat(vendor): the gate lists risky changes (dependencies, CI) in checks.md"
scripts/known-hashes
git add tests/test_risky.py vendor/known-hashes.json
git commit -m "test: risky paths in the gate; refresh known hashes"
```

---

### Task 3: Risky changes stop at merge; `factory:risk-ok` lets them through

**Files:**
- Modify: `vendor/factory/factory/bin/job`
- Test: `tests/test_risky.py`

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_risky.py`:

```python
import contextlib
import io

from budget_case import BudgetCase

RISKY_CHECKS = ("GATE: PASS\nCOMMIT: abc\n\n## Summary\n- ok\n\n## Protected paths\nNone changed.\n\n"
                "## Risky changes\n- M package.json\n- A .github/workflows/ci.yml\n\n## checks.sh\nExit 0\n")


class RiskyMergeTest(BudgetCase):
    def approved(self, checks=RISKY_CHECKS):
        self.in_review()
        self.advance("approve")
        (self.d / "decision.md").write_text("APPROVE\n")
        (self.d / "round-1" / "checks.md").write_text(checks)

    def merge(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_merge(self.current())
        return out.getvalue()

    def test_risky_listed_reads_checks_md(self):
        self.approved()
        self.assertEqual(self.job.risky_listed(self.current()), ["M package.json", "A .github/workflows/ci.yml"])

    def test_merge_stops_without_risk_ok(self):
        self.approved()
        out = self.merge()
        job = self.current()
        self.assertEqual(job["stage"], "needs-human")
        self.assertTrue(job["risk_stopped"])
        self.assertIn("changes dependencies or CI: M package.json", (self.d / "decision.md").read_text())
        self.assertIn("factory:risk-ok", out)

    def test_risk_ok_label_resumes_and_moves_back_to_merging(self):
        self.approved()
        self.merge()
        self.issues = [{"number": 7, "title": "Build the widget"}]
        self.project.issue["labels"].append({"name": "factory:risk-ok"})
        queue = io.StringIO()
        with contextlib.redirect_stdout(queue):
            self.job.cmd_queue()
        self.assertIn("resume\t7", queue.getvalue())
        self.assertIn("factory:risk-ok added", queue.getvalue())
        job = self.advance("merging")
        self.assertEqual(job["stage"], "merging")
        self.assertNotIn("risk_stopped", job)

    def test_no_risk_ok_no_way_back_to_merging(self):
        self.approved()
        self.merge()
        with self.assertRaisesRegex(self.job.Refused, "add the factory:risk-ok label"):
            self.advance("merging")

    def test_other_needs_human_jobs_cannot_jump_to_merging(self):
        self.in_review()
        job = self.current()
        self.job.stop_for_human(job, "something else")
        with self.assertRaisesRegex(self.job.Refused, "only a job stopped for risky changes"):
            self.advance("merging")

    def test_no_risky_section_means_no_stop(self):
        self.approved(checks="GATE: PASS\n\n## Risky changes\nNone.\n")
        self.assertEqual(self.job.risky_listed(self.current()), [])
```

`BudgetCase.fake_gh_json` returns `{"state": "OPEN", ...}` for `pr view`, so after the risky stop the merge doesn't go further. Both tests above stop before any `git` call in the worktree.

- [ ] **Step 2: Run them and see them fail** (`no attribute 'risky_listed'`).

- [ ] **Step 3: Implement.** In `job`, add `"merging"` to `needs-human` in `TRANSITIONS`:

```python
    "needs-human": {"build", "rejected", "merging"},
```

Add after `paused_line`/`cmd_resume`:

```python
def risk_ok_label():
    return LABELS.get("risk_ok", "factory:risk-ok")


def risky_listed(job):
    """`- <status> <path>` lines under `## Risky changes` in the current round's checks.md."""
    path = round_dir(job) / "checks.md"
    body = section(path, "Risky changes") if path.exists() else None
    return [line[2:].strip() for line in (body or "").splitlines() if line.startswith("- ")]


def has_risk_ok(job):
    return risk_ok_label() in {l["name"] for l in fetch_issue(job["issue"])["labels"]}
```

In `advance`, add a branch **before** the existing `elif old == "needs-human":` branch:

```python
    elif old == "needs-human" and stage == "merging":
        require(job.get("risk_stopped"), "only a job stopped for risky changes can go back to merging")
        require(has_risk_ok(job), f"add the {risk_ok_label()} label to issue #{job['issue']} first")
        job.pop("risk_stopped")
        label("issue", job["issue"], remove=LABELS["needs_human"])
```

In `cmd_merge`, right after the `if job.get("feedback_pending") or pr_comments(job): return fail(unhandled)` lines, add:

```python
    risky = risky_listed(job)
    if risky and not has_risk_ok(job):
        job["risk_stopped"] = True
        return fail(f"This PR changes dependencies or CI: {', '.join(risky)}. Review it, then add "
                    f"`{risk_ok_label()}` to the issue and run the factory again, or merge it yourself.")
```

In `cmd_queue`, change the needs-human branch that appends a `wait` row so a risk-stopped job whose issue now has the label resumes:

```python
        elif j["stage"] == "needs-human" and j.get("risk_stopped") and has_risk_ok(j):
            replied_rows.append(("resume", n, j["id"], j["stage"], f"{risk_ok_label()} added"))
        elif j["stage"] == "needs-human":
```

(placed right before the existing `elif j["stage"] == "needs-human":` that builds the `merge PR #…` wait row).

- [ ] **Step 4: Run them and see them pass.** `python3 -m unittest tests/test_risky.py tests/test_budgets.py tests/test_run_fixes.py -v`

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/factory/bin/job
git commit -m "feat(vendor): risky changes stop at merge until the issue has factory:risk-ok"
scripts/known-hashes
git add tests/test_risky.py vendor/known-hashes.json
git commit -m "test: risky merge stop and risk-ok resume; refresh known hashes"
```

---

### Task 4: Secret scan, `job push`, and the gate backstop

**Files:**
- Modify: `vendor/factory/factory/bin/job`, `vendor/factory/factory/bin/gate`, `vendor/factory/factory/config.json`, `vendor/factory/.claude/agents/builder.md`
- Create: `tests/test_secret_scan.py`

- [ ] **Step 1: Write the failing tests.** `tests/test_secret_scan.py`:

```python
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from factory_project import FactoryProject, git

# Built at runtime so no secret-looking literal sits in the repo.
SAMPLES = {
    "private key": "-----BEGIN " + "RSA PRIVATE KEY-----",
    "aws access key": "AKIA" + "Q" * 16,
    "github token": "ghp_" + "a1" * 18,
    "anthropic key": "sk-" + "ant-" + "x" * 24,
    "slack token": "xox" + "b-" + "1" * 12,
    "assigned secret": "api_key = '" + "z" * 20 + "'",
}


class SecretScanTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        self.job = self.project.load_job()
        self.wt = Path(tmp.name) / "wt"
        git(self.project.repo, "worktree", "add", "-q", "-b", "factory/001-x", str(self.wt), "origin/main")

    def commit(self, files):
        for rel, text in files.items():
            (self.wt / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.wt / rel).write_text(text)
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "-m", "change")

    def test_each_rule_hits_and_masks_the_value(self):
        self.commit({"conf.py": "x = 1\n" + "\n".join(SAMPLES.values()) + "\n"})
        hits = self.job.secret_hits(self.wt)
        self.assertEqual([h.split(" ", 1)[1].split(":")[0] for h in hits], list(SAMPLES))
        self.assertTrue(hits[0].startswith("conf.py:2 "))
        for hit, value in zip(hits, SAMPLES.values()):
            self.assertNotIn(value, hit)
            self.assertIn("chars)", hit)

    def test_allow_globs_and_removed_lines_are_skipped(self):
        self.commit({"tests/fixtures/keys.txt": SAMPLES["aws access key"] + "\n",
                     "app.test.js": SAMPLES["github token"] + "\n"})
        self.assertEqual(self.job.secret_hits(self.wt), [])

    def test_push_refuses_on_a_hit_and_pushes_when_clean(self):
        job = {"id": "001-x", "stage": "build", "worktree": str(self.wt), "branch": "factory/001-x"}
        self.commit({"conf.py": SAMPLES["aws access key"] + "\n"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            self.job.cmd_push(job)
        self.assertIn("SECRET: conf.py:1 aws access key", out.getvalue())
        self.assertEqual(git(self.project.repo, "ls-remote", "origin", "factory/001-x"), "")
        self.commit({"conf.py": "key = load_from_env()\n"})
        git(self.wt, "reset", "-q", "--soft", "HEAD~2")
        git(self.wt, "commit", "-q", "-m", "clean")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_push(job)
        self.assertIn("PUSHED: factory/001-x", out.getvalue())
        self.assertNotEqual(git(self.project.repo, "ls-remote", "origin", "factory/001-x"), "")

    def test_gate_found_secrets_reads_checks_md(self):
        d = self.job.job_dir("001-x")
        (d / "round-1").mkdir(parents=True)
        job = {"id": "001-x", "round": 1}
        (d / "round-1" / "checks.md").write_text("GATE: FAIL\n\n## Secrets\nNone found.\n")
        self.assertFalse(self.job.gate_found_secrets(job))
        (d / "round-1" / "checks.md").write_text("GATE: FAIL\n\n## Secrets\n- conf.py:1 aws access key: AKIA… (20 chars)\n")
        self.assertTrue(self.job.gate_found_secrets(job))
```

- [ ] **Step 2: Run them and see them fail** (`no attribute 'secret_hits'`).

- [ ] **Step 3: Config.** In `vendor/factory/factory/config.json` add after `risky_paths`:

```json
  "secret_scan": { "allow": ["**/*.test.*", "**/fixtures/**"] },
```

- [ ] **Step 4: Implement in `job`.** Add a section after the risky helpers:

```python
# ---- Secret scan -------------------------------------------------------------

SECRET_RULES = (
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,}")),
    ("anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("assigned secret", re.compile(r"(api[_-]?key|secret|token|password)\s*[:=]\s*[\"'][^\"']{16,}[\"']", re.I)),
)
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
SECRET_WHY = ("A possible secret reached the remote branch (see `## Secrets` in this round's checks.md). "
              "Rotate it, then remove it from the branch history before giving feedback.")


def path_matches(path, pattern):
    """fnmatch (whose * also crosses /), plus `**/x` matching `x` at the root. Same as the gate's."""
    return fnmatch.fnmatch(path, pattern) or (pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:]))


def added_lines(diff):
    """(path, new line number, text) for every added line of a unified diff."""
    path, line = None, 0
    for text in diff.splitlines():
        if text.startswith("+++ "):
            path = text[6:] if text.startswith("+++ b/") else None
            continue
        m = HUNK.match(text)
        if m:
            line = int(m.group(1))
            continue
        if path is None or text.startswith("--- "):
            continue
        if text.startswith("+"):
            yield path, line, text[1:]
            line += 1
        elif text.startswith(" "):
            line += 1


def mask(value):
    return f"{value[:4]}… ({len(value)} chars)"


def secret_hits(worktree):
    """`path:line rule: masked` for each added line on the branch that matches a secret rule."""
    allow = (CONFIG.get("secret_scan") or {}).get("allow", ["**/*.test.*", "**/fixtures/**"])
    diff = run(["git", "diff", "--no-color", "--unified=0", f"origin/{BASE}...HEAD"], cwd=worktree).stdout
    hits = []
    for path, n, text in added_lines(diff):
        if any(path_matches(path, pattern) for pattern in allow):
            continue
        for name, rule in SECRET_RULES:
            m = rule.search(text)
            if m:
                hits.append(f"{path}:{n} {name}: {mask(m.group(0))}")
                break
    return hits


def cmd_scan(job):
    hits = secret_hits(job["worktree"])
    for hit in hits:
        print(f"SECRET: {hit}")
    if hits:
        sys.exit(1)
    print("SCAN: clean")


def cmd_push(job):
    require(job["stage"] == "build", f"{job['id']} is in {job['stage']}; only the builder pushes, in build")
    git(job, "fetch", "origin", BASE)
    hits = secret_hits(job["worktree"])
    if hits:
        for hit in hits:
            print(f"SECRET: {hit}")
        print("Nothing was pushed. Remove the secret from your commits (amend or rebase; the branch "
              "isn't pushed yet), then run factory/bin/job push again.")
        sys.exit(1)
    git(job, "push", "-u", "origin", job["branch"])
    print(f"PUSHED: {job['branch']}")


def gate_found_secrets(job):
    body = section(round_dir(job) / "checks.md", "Secrets") if (round_dir(job) / "checks.md").exists() else None
    return bool(body) and body != "None found."
```

Add `import fnmatch` to the imports at the top of `job`.

In `advance`, right after the paused-merging guard from Task 1, add:

```python
    if old == "gate" and stage == "build" and gate_found_secrets(job):
        stop_for_human(job, SECRET_WHY)
        return job
```

Usage lines and `main` dispatch:

```
  job scan <job>                 secret patterns in the branch's added lines; exit 1 on a hit
  job push <job>                 the builder's push: scan, then push the job branch (nothing is pushed on a hit)
```

```python
        elif cmd == "scan" and len(args) == 1:
            cmd_scan(resolve(args[0]))
        elif cmd == "push" and len(args) == 1:
            cmd_push(resolve(args[0]))
```

- [ ] **Step 5: Gate backstop.** In `vendor/factory/factory/bin/gate`, add after `risky_changes`:

```python
def secret_scan(job_id):
    """Masked SECRET lines from `job scan`; the gate never prints a secret itself."""
    res = subprocess.run([sys.executable, str(FACTORY / "bin" / "job"), "scan", job_id], cwd=REPO,
                         capture_output=True, text=True)
    if res.returncode not in (0, 1):
        die(f"job scan failed: {(res.stderr or res.stdout).strip()}")
    return [line.removeprefix("SECRET: ") for line in res.stdout.splitlines() if line.startswith("SECRET: ")]
```

In `gate()`, after `risky = ...`: `secrets = secret_scan(job_id)`; change the verdict to

```python
    verdict = "PASS" if code == 0 and not protected and not secrets else "FAIL"
```

add a summary bullet `f"Secrets: {len(secrets)} found" if secrets else "Secrets: none found"`, and after the `## Risky changes` section in `checks.md`:

```python
        + "\n\n## Secrets\n"
        + ("\n".join(f"- {s}" for s in secrets) if secrets else "None found.")
```

- [ ] **Step 6: Builder prompt.** In `vendor/factory/.claude/agents/builder.md`, **Commit, push, PR**, replace the bullet

```
- Push with `git push -u origin <branch>`. Push only the job branch, never
  anything else.
```

with

```
- Push with `cd <main checkout> && factory/bin/job push <job-id>`. It scans
  your branch for secrets first. If it prints `SECRET:` lines, nothing was
  pushed: remove the secret from your commits (amend or rebase locally; the
  branch isn't pushed yet) and run it again. Never push any other way, and
  never push anything but the job branch.
```

Add to `tests/test_secret_scan.py`:

```python
class BuilderWordingTest(unittest.TestCase):
    def test_builder_pushes_through_job_push(self):
        text = (Path(__file__).resolve().parents[1] / "vendor/factory/.claude/agents/builder.md").read_text()
        self.assertIn("factory/bin/job push <job-id>", text)
        self.assertNotIn("git push -u origin <branch>", text)
```

- [ ] **Step 7: Run the tests and see them pass.** `python3 -m unittest tests/test_secret_scan.py tests/test_risky.py tests/test_gate_plan_paths.py -v`, then `scripts/check`.

- [ ] **Step 8: Commit** (three vendored commits, then the plugin side).

```bash
git add vendor/factory/factory/bin/job vendor/factory/factory/config.json
git commit -m "feat(vendor): job scan and job push block secrets before they leave the machine"
git add vendor/factory/factory/bin/gate
git commit -m "feat(vendor): the gate repeats the secret scan and fails on a hit"
git add vendor/factory/.claude/agents/builder.md
git commit -m "feat(vendor): the builder pushes through job push"
scripts/known-hashes
git add tests/test_secret_scan.py vendor/known-hashes.json
git commit -m "test: secret scan, job push and the gate backstop; refresh known hashes"
```

---

### Task 5: Watching the base branch

**Files:**
- Modify: `vendor/factory/factory/bin/job`, `vendor/factory/factory/config.json`
- Create: `tests/test_watch.py`

- [ ] **Step 1: Write the failing tests.** `tests/test_watch.py`:

```python
import contextlib
import io
import unittest
from datetime import datetime, timedelta, timezone

from budget_case import BudgetCase


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class WatchVerdictTest(BudgetCase):
    def verdict(self, runs, minutes=5, **cfg):
        since = iso(datetime.now(timezone.utc) - timedelta(minutes=minutes))
        return self.job.watch_verdict(runs, {**self.job.watch_config(), **cfg}, since)[0]

    def test_states(self):
        ok = {"status": "completed", "conclusion": "success", "workflowName": "ci", "url": "u"}
        self.assertEqual(self.verdict([ok, {**ok, "conclusion": "skipped"}]), "green")
        self.assertEqual(self.verdict([ok, {**ok, "status": "in_progress", "conclusion": ""}]), "watching")
        self.assertEqual(self.verdict([ok, {**ok, "conclusion": "failure"}]), "red")
        self.assertEqual(self.verdict([{**ok, "conclusion": "timed_out"}]), "red")
        self.assertEqual(self.verdict([{**ok, "conclusion": "failure", "workflowName": "nightly"}],
                                      ignore_workflows=["nightly"]), "watching")
        self.assertEqual(self.verdict([]), "watching")
        self.assertEqual(self.verdict([], minutes=61), "no-ci")


class WatchCommandTest(BudgetCase):
    def setUp(self):
        super().setUp()
        self.runs = []
        self.reverted = []
        base = self.fake_gh_json

        def gh_json(*args):
            if args[:2] == ("run", "list"):
                return list(self.runs)
            if args[:2] == ("pr", "view") and "mergeCommit" in args:
                return {"mergeCommit": {"oid": "f" * 40}}
            return base(*args)

        self.job.gh_json = gh_json
        self.job.revert_for = lambda job, failed: self.reverted.append((job["id"], failed))
        job = self.job.load(self.job_id)
        job.update({"stage": "merged", "pr": 12, "watch": {"sha": "f" * 40, "since": iso(datetime.now(timezone.utc)),
                                                          "state": "watching"}})
        self.job.save(job)

    def watch(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_watch()
        return out.getvalue()

    def test_green_is_recorded(self):
        self.runs = [{"status": "completed", "conclusion": "success", "workflowName": "ci", "url": "u"}]
        self.assertIn(f"WATCH: {self.job_id} green", self.watch())
        self.assertEqual(self.current()["watch"]["state"], "green")

    def test_red_hands_over_to_revert(self):
        self.runs = [{"status": "completed", "conclusion": "failure", "workflowName": "ci", "url": "u"}]
        self.watch()
        self.assertEqual(self.reverted[0][0], self.job_id)

    def test_gh_failure_keeps_watching(self):
        def boom(*args):
            raise self.job.Refused("gh: offline")
        self.job.gh_json = boom
        self.assertIn("NOTE:", self.watch())
        self.assertEqual(self.current()["watch"]["state"], "watching")

    def test_off(self):
        self.job.CONFIG["watch"] = {"enabled": False}
        self.assertIn("WATCH: off", self.watch())

    def test_merge_records_the_watch(self):
        job = {"pr": 12}
        self.job.record_watch(job)
        self.assertEqual(job["watch"]["sha"], "f" * 40)
        self.assertEqual(job["watch"]["state"], "watching")
```

- [ ] **Step 2: Run them and see them fail** (`no attribute 'watch_verdict'`).

- [ ] **Step 3: Config.** Add after `digest` in `vendor/factory/factory/config.json`:

```json
  "watch": { "enabled": true, "max_minutes": 60, "ignore_workflows": [] },
```

- [ ] **Step 4: Implement.** In `job`, after the secret-scan section:

```python
# ---- Watching the base branch -------------------------------------------------

WATCH_DEFAULTS = {"enabled": True, "max_minutes": 60, "ignore_workflows": []}
RED_CONCLUSIONS = {"failure", "timed_out", "cancelled"}


def watch_config():
    return {**WATCH_DEFAULTS, **(CONFIG.get("watch") or {})}


def record_watch(job):
    """After a merge: remember the commit that landed on the base branch, to watch its CI."""
    if not watch_config()["enabled"]:
        return
    try:
        sha = gh_json("pr", "view", str(job["pr"]), "--json", "mergeCommit")["mergeCommit"]["oid"]
    except (Refused, KeyError, TypeError) as e:
        print(f"NOTE: not watching {BASE} after #{job['pr']}: {str(e).splitlines()[0] if str(e) else e!r}")
        return
    job["watch"] = {"sha": sha, "since": now(), "state": "watching"}


def watch_verdict(runs, cfg, since):
    """(state, failed runs) for a merge commit's workflow runs on the base branch."""
    runs = [r for r in runs if r.get("workflowName") not in cfg["ignore_workflows"]]
    failed = [r for r in runs if r.get("conclusion") in RED_CONCLUSIONS]
    if failed:
        return "red", failed
    if runs and all(r.get("status") == "completed" for r in runs):
        return "green", []
    minutes = (datetime.now(timezone.utc) - parse_time(since)).total_seconds() / 60
    if not runs and minutes > cfg["max_minutes"]:
        return "no-ci", []
    return "watching", []


def cmd_watch():
    cfg = watch_config()
    if not cfg["enabled"]:
        print("WATCH: off")
        return
    for job in all_jobs():
        w = job.get("watch") or {}
        if w.get("state") != "watching":
            continue
        try:
            runs = gh_json("run", "list", "--branch", BASE, "--commit", w["sha"], "--limit", "50",
                           "--json", "status,conclusion,workflowName,url")
        except Refused as e:
            print(f"NOTE: {job['id']}: {BASE} checks unknown, still watching: {str(e).splitlines()[0]}")
            continue
        state, failed = watch_verdict(runs, cfg, w["since"])
        if state == "watching":
            continue
        if state == "red":
            revert_for(job, failed)
            continue
        job["watch"] = {**w, "state": state}
        save(job)
        print(f"WATCH: {job['id']} {state}" + (f"; no CI runs on {BASE} within {cfg['max_minutes']} min" if state == "no-ci" else ""))


def revert_for(job, failed):
    """Replaced in Task 6."""
    raise Refused("revert isn't implemented yet")
```

In `cmd_merge`, just before the final `save(advance(sync(job), "merged"))` after a successful merge (the one followed by `print(... merged PR ...)` and `sync_main()`), add:

```python
    record_watch(job)
```

Usage and `main`:

```
  job watch                      check base-branch CI for merged jobs; red → revert PR and pause
```

```python
        elif cmd == "watch" and not args:
            cmd_watch()
```

- [ ] **Step 5: Run them and see them pass.** `python3 -m unittest tests/test_watch.py -v`

- [ ] **Step 6: Commit.**

```bash
git add vendor/factory/factory/bin/job vendor/factory/factory/config.json
git commit -m "feat(vendor): job watch follows base-branch CI after each factory merge"
scripts/known-hashes
git add tests/test_watch.py vendor/known-hashes.json
git commit -m "test: watch states and recording; refresh known hashes"
```

---

### Task 6: The revert procedure

**Files:**
- Modify: `vendor/factory/factory/bin/job`
- Create: `tests/test_revert.py`

- [ ] **Step 1: Write the failing tests.** `tests/test_revert.py` (real git, a bare origin, `gh` faked):

```python
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from factory_project import FactoryProject, git

FAILED = [{"workflowName": "ci", "url": "https://github.com/o/r/actions/runs/1", "conclusion": "failure"}]


class RevertCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        self.job = self.project.load_job()
        self.calls = []

        def fake_gh(*args):
            self.calls.append(args)
            if args[:2] == ("pr", "create"):
                return "https://github.com/o/r/pull/44\n"
            return ""

        self.job.gh = fake_gh
        self.job.gh_json = lambda *args: {"commits": [{}, {}]}

    def land(self, merge_commit):
        """Put a 'PR' on origin/main, the way GitHub would merge it; returns the sha that landed."""
        repo = self.project.repo
        git(repo, "checkout", "-q", "-b", "feature")
        (repo / "widget.txt").write_text("spins\n")
        git(repo, "add", "widget.txt")
        git(repo, "commit", "-q", "-m", "add widget")
        git(repo, "checkout", "-q", "main")
        if merge_commit:
            git(repo, "merge", "-q", "--no-ff", "-m", "Merge pull request #12", "feature")
        else:
            git(repo, "merge", "-q", "--squash", "feature")
            git(repo, "commit", "-q", "-m", "Add widget (#12)")
        git(repo, "push", "-q", "origin", "main")
        return git(repo, "rev-parse", "HEAD")

    def job_record(self, sha):
        return {"id": "001-widget", "issue": 7, "pr": 12, "title": "Add widget",
                "watch": {"sha": sha, "since": "2026-11-13T00:00:00Z", "state": "watching"}}

    def revert_branch_files(self):
        git(self.project.repo, "fetch", "-q", "origin")
        return git(self.project.repo, "ls-tree", "--name-only", "origin/factory/revert-001-widget")


class OpenRevertTest(RevertCase):
    def test_squash_merge_is_reverted_on_a_new_branch(self):
        self.job.CONFIG["merge_method"] = "squash"
        sha = self.land(merge_commit=False)
        self.assertEqual(self.job.open_revert_pr(self.job_record(sha), FAILED), 44)
        self.assertNotIn("widget.txt", self.revert_branch_files())
        create = next(c for c in self.calls if c[:2] == ("pr", "create"))
        self.assertIn('Revert "Add widget"', create)
        self.assertIn("factory:revert", create)
        self.assertFalse((self.project.repo / ".worktrees" / "revert-001-widget").exists())

    def test_merge_commit_is_reverted_with_mainline_1(self):
        self.job.CONFIG["merge_method"] = "merge"
        sha = self.land(merge_commit=True)
        self.job.open_revert_pr(self.job_record(sha), FAILED)
        self.assertNotIn("widget.txt", self.revert_branch_files())

    def test_a_conflict_opens_nothing(self):
        self.job.CONFIG["merge_method"] = "squash"
        sha = self.land(merge_commit=False)
        (self.project.repo / "widget.txt").write_text("spins faster\n")
        git(self.project.repo, "commit", "-qam", "later change")
        git(self.project.repo, "push", "-q", "origin", "main")
        with self.assertRaisesRegex(self.job.Refused, "didn't apply cleanly"):
            self.job.open_revert_pr(self.job_record(sha), FAILED)
        self.assertFalse(any(c[:2] == ("pr", "create") for c in self.calls))

    def test_revert_command_per_method(self):
        rc = self.job.revert_command
        self.assertEqual(rc("merge", "abc", 1), ["revert", "--no-edit", "-m", "1", "abc"])
        self.assertEqual(rc("squash", "abc", 1), ["revert", "--no-edit", "abc"])
        self.assertEqual(rc("rebase", "abc", 3), ["revert", "--no-edit", "abc~3..abc"])


class RevertForTest(RevertCase):
    def test_red_pauses_comments_labels_and_records(self):
        self.job.CONFIG["merge_method"] = "squash"
        sha = self.land(merge_commit=False)
        self.project.set_issue("Build the widget.", labels=("factory",))
        job_id = self.project.create_job(self.job)
        job = self.job.load(job_id)
        job.update(self.job_record(sha))
        job["id"] = job_id
        self.job.save(job)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.revert_for(self.job.load(job_id), FAILED)
        p = self.job.paused()
        self.assertEqual((p["reason"], p["sha"]), ("main failed after #12 (ci)", sha))
        saved = json.loads((self.job.job_dir(job_id) / "job.json").read_text())
        self.assertEqual((saved["watch"]["state"], saved["watch"]["revert_pr"]), ("red", 44))
        comments = [c for c in self.calls if c[1] == "comment"]
        self.assertEqual({c[0] for c in comments}, {"pr", "issue"})
        self.assertIn("factory/bin/job resume", comments[0][-1])
        self.assertIn(f"WATCH: {job_id} red", out.getvalue())
```

(The `land` helper names the revert branch from `job_record`'s id `001-widget`; `RevertForTest` uses the real job id, so its branch is `factory/revert-<that id>`. The test checks state, not the branch.)

- [ ] **Step 2: Run them and see them fail** (`no attribute 'open_revert_pr'`).

- [ ] **Step 3: Implement.** In `job`, replace the placeholder `revert_for` from Task 5 with:

```python
def revert_label():
    return LABELS.get("revert", "factory:revert")


def revert_command(method, sha, count):
    """git args that undo a PR as it landed: a merge commit, a squash commit, or `count` rebased commits."""
    if method == "merge":
        return ["revert", "--no-edit", "-m", "1", sha]
    if method == "rebase" and count > 1:
        return ["revert", "--no-edit", f"{sha}~{count}..{sha}"]
    return ["revert", "--no-edit", sha]


def open_revert_pr(job, failed):
    """Revert the merge on factory/revert-<id> in a throwaway worktree, push it, open a PR. Never merges."""
    sha, method = job["watch"]["sha"], CONFIG["merge_method"]
    branch = f"factory/revert-{job['id']}"
    path = REPO / ".worktrees" / f"revert-{job['id']}"
    run_net(["git", "fetch", "origin", BASE])
    run(["git", "worktree", "add", "-q", "-b", branch, str(path), f"origin/{BASE}"])
    try:
        count = len(gh_json("pr", "view", str(job["pr"]), "--json", "commits")["commits"]) if method == "rebase" else 1
        res = run(["git", *revert_command(method, sha, count)], cwd=path, check=False)
        if res.returncode != 0:
            run(["git", "revert", "--abort"], cwd=path, check=False)
            raise Refused("the revert didn't apply cleanly")
        run_net(["git", "push", "-u", "origin", branch], cwd=path)
    finally:
        run(["git", "worktree", "remove", "--force", str(path)], check=False)
    gh("label", "create", revert_label(), "--color", "B60205",
       "--description", "Reverts a factory merge that broke the base branch", "--force")
    runs = "\n".join(f"- {r['workflowName']}: {r['url']}" for r in failed)
    url = gh("pr", "create", "--base", BASE, "--head", branch, "--label", revert_label(),
             "--title", f'Revert "{job["title"]}"',
             "--body", f"{MARKER}\nReverts #{job['pr']} ({sha[:7]}): {BASE} failed after it merged.\n\n{runs}\n\n"
                       f"The factory never merges this PR. Merge it, or fix {BASE} forward, "
                       "then run `factory/bin/job resume`.").strip()
    m = re.search(r"/pull/(\d+)$", url)
    require(m, f"gh pr create printed {url!r}, not a PR URL")
    return int(m.group(1))


def revert_for(job, failed):
    """The base branch went red after this job merged: pause, try a revert PR, tell the human."""
    w = job["watch"]
    names = ", ".join(sorted({r["workflowName"] for r in failed}))
    pause(f"{BASE} failed after #{job['pr']} ({names})", job["id"], w["sha"])
    try:
        revert_pr, why = open_revert_pr(job, failed), None
    except Refused as e:
        revert_pr, why = None, str(e).splitlines()[0]
    job["watch"] = {**w, "state": "red", "revert_pr": revert_pr}
    save(job)
    runs = "\n".join(f"- {r['workflowName']}: {r['url']}" for r in failed)
    body = (f"### Factory: {BASE} failed after this merged\n\n{runs}\n\n"
            + (f"Revert PR: #{revert_pr} (not merged automatically).\n\n" if revert_pr
               else f"No revert PR: {why}.\n\n")
            + "The queue is paused; run `factory/bin/job resume` when the base branch is green.")
    for kind, number in (("pr", job["pr"]), ("issue", job["issue"])):
        try:
            comment(kind, number, body)
        except Refused as e:
            print(f"NOTE: couldn't comment on {kind} #{number}: {str(e).splitlines()[0]}")
    try:
        label("issue", job["issue"], add=LABELS["needs_human"])
    except Refused as e:
        print(f"NOTE: couldn't label issue #{job['issue']}: {str(e).splitlines()[0]}")
    print(f"WATCH: {job['id']} red; queue paused; " + (f"revert PR #{revert_pr}" if revert_pr else f"no revert PR: {why}"))
```

- [ ] **Step 4: Run them and see them pass.** `python3 -m unittest tests/test_revert.py tests/test_watch.py -v`

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/factory/bin/job
git commit -m "feat(vendor): a red base branch pauses the queue and opens a revert PR"
scripts/known-hashes
git add tests/test_revert.py vendor/known-hashes.json
git commit -m "test: revert per merge method and on conflict; refresh known hashes"
```

---

### Task 7: Runner, skill, doctor, dashboard, labels

**Files:**
- Modify: `vendor/factory/factory/bin/runner`, `vendor/factory/.claude/skills/factory/SKILL.md`, `vendor/factory/factory/bin/doctor`, `vendor/factory/factory/dashboard.html`, `skills/factory-install/SKILL.md`, `skills/factory-uninstall/SKILL.md`, `tests/installed_project.py`, `tests/test_doctor.py`, `tests/test_runner.py`
- Create: `tests/test_safety_wording.py`

- [ ] **Step 1: Write the failing tests.**

`tests/installed_project.py`: add `"factory:revert", "factory:risk-ok"` to the end of `LABELS`.

Append to the doctor test class that has `test_missing_digest_label_fails`:

```python
    def test_missing_revert_and_risk_ok_labels_fail(self):
        self.p.set_labels([n for n in LABELS if n not in ("factory:revert", "factory:risk-ok")])
        res = self.p.run("doctor", "--fast")
        self.assertIn("label 'factory:revert' missing", res.stdout)
        self.assertIn("label 'factory:risk-ok' missing", res.stdout)

    def test_paused_is_a_warning_with_the_reason(self):
        self.p.write("factory/jobs/paused.json", json.dumps({"reason": "main is red", "time": "t"}))
        self.assertIn("WARN paused: main is red", self.p.run("doctor", "--fast").stdout)

    def test_bad_safety_config_fails(self):
        cfg = json.loads((self.p.root / "factory/config.json").read_text())
        cfg.update(watch={"enabled": 1, "max_minutes": 0, "ignore_workflows": "x"}, risky_paths="x",
                   secret_scan={"allow": [1]})
        self.p.write("factory/config.json", json.dumps(cfg))
        out = self.p.run("doctor", "--fast").stdout
        for text in ("watch.enabled", "watch.max_minutes", "watch.ignore_workflows", "risky_paths",
                     "secret_scan.allow"):
            self.assertIn(text, out)
```

Append to `TickTest` in `tests/test_runner.py`:

```python
    def test_paused_tick_is_idle_and_does_not_call_claude(self):
        self.set_issues([{"number": 7, "title": "x"}])
        (self.p.root / "factory/jobs").mkdir(parents=True, exist_ok=True)
        (self.p.root / "factory/jobs/paused.json").write_text(json.dumps({"reason": "red", "time": "t"}))
        res = self.runner("tick")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.calls("claude"), [])
        self.assertTrue(self.log_lines()[-1].endswith("idle"))
```

(If the fake `claude` in this file doesn't record into `calls("claude")`, assert the same way the existing `test_idle_queue_does_not_call_claude` does.)

`tests/test_safety_wording.py`:

```python
import unittest
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[1] / "vendor/factory"


class SafetyWordingTest(unittest.TestCase):
    def test_skill_watches_first_and_respects_the_pause(self):
        text = (VENDOR / ".claude/skills/factory/SKILL.md").read_text()
        self.assertIn("factory/bin/job watch", text)
        self.assertIn("PAUSED:", text)
        self.assertIn("factory/bin/job resume", text)
        self.assertIn("factory:risk-ok added", text)

    def test_runner_watches_in_its_chores(self):
        text = (VENDOR / "factory/bin/runner").read_text()
        self.assertIn('["watch"]', text)

    def test_dashboard_shows_the_pause(self):
        self.assertIn("jobs/paused.json", (VENDOR / "factory/dashboard.html").read_text())

    def test_install_and_uninstall_handle_the_labels(self):
        root = Path(__file__).resolve().parents[1] / "skills"
        install = (root / "factory-install/SKILL.md").read_text()
        uninstall = (root / "factory-uninstall/SKILL.md").read_text()
        for name in ("factory:revert", "factory:risk-ok"):
            self.assertIn(f"gh label create {name}", install)
            self.assertIn(f"gh label delete {name} --yes", uninstall)
```

- [ ] **Step 2: Run them and see them fail.** `python3 -m unittest tests/test_doctor.py tests/test_runner.py tests/test_safety_wording.py -v`

- [ ] **Step 3: Runner.** In `vendor/factory/factory/bin/runner`, `chores()`, make `["watch"]` the first item:

```python
    for args in (["watch"], ["report", "--write"], ["digest"]):
```

and update its docstring to "Watch, report and digest: …".

- [ ] **Step 4: Skill.** In `vendor/factory/.claude/skills/factory/SKILL.md`, **/factory run**:

- Insert a new first step and renumber the rest:

```markdown
1. Run `factory/bin/job watch`. Report every line except `WATCH: off`. A
   `WATCH: <id> red` line means the base branch failed after that job merged:
   the script has paused the queue and opened a revert PR (or said why not).
   Tell the user; never merge the revert PR yourself.
```

- In the step that runs `factory/bin/job queue`, add: "If its first line starts with `PAUSED:`, start nothing: tell the user the reason and that `factory/bin/job resume` clears it once the base branch is fixed. Finish any agents already running, but `job merge` refuses while paused."
- In **Resuming**, add: "A `needs-human` job with the note `factory:risk-ok added` was stopped at merge for risky changes, and a human has since approved them: run `factory/bin/job advance <id> merging`, then `factory/bin/job merge <id>`."

In **/factory <anything>**, add a bullet:

```markdown
- **Resuming the queue** after a pause: only when the user asks, run
  `factory/bin/job resume` and show its `RESUME:` line.
```

- [ ] **Step 5: Doctor.** In `vendor/factory/factory/bin/doctor`:

```python
LABELS = ("factory", "factory:needs-info", "factory:needs-human", "factory:planned",
          "factory:learning", "factory:digest", "factory:revert", "factory:risk-ok")
```

In `check_config`, before the `agents.learner` check, add:

```python
    watch = cfg.get("watch")
    if watch is not None:
        if not isinstance(watch, dict):
            problems.append(fail("watch must be an object with enabled, max_minutes and ignore_workflows"))
        else:
            if not isinstance(watch.get("enabled", True), bool):
                problems.append(fail("watch.enabled must be true or false"))
            mins = watch.get("max_minutes", 60)
            if isinstance(mins, bool) or not isinstance(mins, int) or mins <= 0:
                problems.append(fail("watch.max_minutes must be a positive integer"))
            names = watch.get("ignore_workflows", [])
            if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
                problems.append(fail("watch.ignore_workflows must be a list of workflow names"))
    risky = cfg.get("risky_paths", [])
    if not isinstance(risky, list) or not all(isinstance(p, str) and p for p in risky):
        problems.append(fail("risky_paths must be a list of glob strings"))
    allow = (cfg.get("secret_scan") or {}).get("allow", []) if isinstance(cfg.get("secret_scan", {}), dict) else None
    if not isinstance(allow, list) or not all(isinstance(p, str) and p for p in allow):
        problems.append(fail("secret_scan.allow must be a list of glob strings"))
```

Add a check after `check_labels`:

```python
def check_paused():
    path = REPO / "factory" / "jobs" / "paused.json"
    if not path.exists():
        return []
    try:
        reason = json.loads(path.read_text()).get("reason", "?")
    except ValueError:
        reason = "paused.json is unreadable"
    return [warn(f"{reason}; factory/bin/job resume clears it once the base branch is fixed")]
```

and add `("paused", check_paused),` to `CHECKS` after `("labels", check_labels),`. Then in `tests/test_doctor.py`, add `"paused"` after `"labels"` in `CHECK_NAMES` if a test iterates it to expect a PASS line for every check.

- [ ] **Step 6: Dashboard.** In `vendor/factory/factory/dashboard.html`, in `render()`, before `const banner = ...`, read the pause file and put it first among the banner problems:

```javascript
  try {
    const p = JSON.parse(await fetchText('jobs/paused.json'))
    problems.unshift(`Queue paused: ${p.reason} (since ${p.time}). Run factory/bin/job resume once it's fixed.`)
  } catch { /* not paused */ }
```

- [ ] **Step 7: Install and uninstall skills.** In `skills/factory-install/SKILL.md` **Step 2 (Adapt), labels**, add:

```bash
gh label create factory:revert --color B60205 --description "Reverts a factory merge that broke the base branch"
gh label create factory:risk-ok --color FBCA04 --description "A human reviewed this issue's risky changes; the factory may merge them"
```

In `skills/factory-uninstall/SKILL.md`, add after the digest label line:

```bash
    gh label delete factory:revert --yes
    gh label delete factory:risk-ok --yes
```

- [ ] **Step 8: Run the tests and see them pass**, then `scripts/check`.

- [ ] **Step 9: Commit** (one commit per vendored file, then the plugin side).

```bash
git add vendor/factory/factory/bin/runner
git commit -m "feat(vendor): runner watches the base branch every tick"
git add vendor/factory/.claude/skills/factory/SKILL.md
git commit -m "feat(vendor): factory skill watches first, respects the pause, resumes risk-ok jobs"
git add vendor/factory/factory/bin/doctor
git commit -m "feat(vendor): doctor checks the safety labels and config and warns when paused"
git add vendor/factory/factory/dashboard.html
git commit -m "feat(vendor): dashboard shows when the queue is paused"
scripts/known-hashes
git add skills/factory-install/SKILL.md skills/factory-uninstall/SKILL.md tests/installed_project.py \
  tests/test_doctor.py tests/test_runner.py tests/test_safety_wording.py vendor/known-hashes.json
git commit -m "feat: install the revert and risk-ok labels; tests; refresh known hashes"
```

---

### Task 8: README and the e2e scenario

**Files:**
- Modify: `README.md`, `tests/test_e2e_scenarios.py`
- Create: `tests/e2e/risky-change/scenario.json`

- [ ] **Step 1: README.** Replace nothing; add under `## Safety: what stays with you`:

```markdown
### After the merge

- **Watching the base branch.** After each merge the factory watches the
  workflow runs on the merged commit (`watch` in `factory/config.json`). If
  one fails, it pauses the queue, opens a `Revert "<title>"` PR labeled
  `factory:revert`, and comments on the original PR and issue. It never merges
  the revert. Merge it or fix forward, then run `factory/bin/job resume`.
- **Pausing by hand.** `factory/bin/job pause <reason>` stops new work and
  merges; `factory/bin/job resume` clears it. `doctor`, `job summary` and the
  dashboard show the pause.
- **Risky changes.** A PR that changes files matching `risky_paths`
  (dependencies, lock files, CI workflows, Dockerfiles, Terraform) is reviewed
  as usual but stops before merging. Review it, add `factory:risk-ok` to the
  issue and run `/factory run` again, or merge it yourself.
- **Secrets.** The builder pushes with `factory/bin/job push`, which refuses
  to push added lines that look like private keys or tokens. The gate scans
  again; a hit there stops the job and asks you to rotate the secret. This is a
  backstop, not a replacement for GitHub secret scanning.
```

- [ ] **Step 2: The scenario.** `tests/e2e/risky-change/scenario.json`:

```json
{
  "title": "Pin the test runner in requirements-dev.txt",
  "issue_body": "Add a `requirements-dev.txt` that pins the test tooling this project uses, and mention it in the README.",
  "labels": ["factory"],
  "config_patch": {},
  "expect": {"stage": "needs-human", "decision_prefix": "ESCALATE", "pr_state": "OPEN"},
  "timeout_minutes": 60
}
```

Add `"risky-change"` to the sorted list in `tests/test_e2e_scenarios.py`:

```python
        self.assertEqual(names, ["budget-stop", "happy-path", "learning", "needs-info", "report",
                                 "risky-change", "runner-tick", "tagged-finding"])
```

- [ ] **Step 3: Check.** `scripts/check`

- [ ] **Step 4: Commit.**

```bash
git add README.md tests/e2e/risky-change/scenario.json tests/test_e2e_scenarios.py
git commit -m "docs: safety after the merge; e2e risky-change scenario"
```

---

## For the human after merge

- Run `/factory-update` here. Then create the labels once:
  `gh label create factory:revert --color B60205` and `gh label create factory:risk-ok --color FBCA04`.
- Add the `factory` label to the Phase 5a issue.
