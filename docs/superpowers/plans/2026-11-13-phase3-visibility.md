# Phase 3: Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `job report` (spend, throughput, what needs you, escalations, findings, gate pass rate), a daily digest comment on a pinned `factory:digest` issue, a "What needs me?" README section, and a summary strip on the dashboard.

**Architecture:**
- **Vendored `factory/bin/job`:** `report_data()` builds one dict from `factory/jobs/` only (no GitHub calls). `report_md()` renders it. `job report [--days N] [--json] [--write]` prints it and can write `factory/jobs/report.json`. `job digest` posts the markdown on the digest issue at most once every 20 hours, after `digest.hour`.
- **Vendored `factory/bin/runner`:** every tick, after the pull and before the queue check, runs `job report --write` and `job digest`. Neither runs a Claude session.
- **Vendored skill, config, doctor and dashboard:** `/factory run` ends with both commands and `/factory report` prints the report. Config gains `digest`, doctor validates it and checks the `factory:digest` label, and the dashboard shows a strip from `report.json`.
- **Plugin side:** the install and uninstall skills, test helpers, a README section, and an e2e scenario.

**Tech Stack:** Python 3.10+ stdlib, `unittest`, the `gh` CLI (faked in tests).

**Spec:** `docs/superpowers/specs/2026-11-13-phase3-visibility-design.md`

**Rules for this plan:**
- Never edit the spec or this plan. Make no git tags. Push nothing but the job branch.
- Make every vendored edit in its own commit (`feat(vendor): …` / `fix(vendor): …`), then a plugin-side commit with its tests and the refreshed `vendor/known-hashes.json` (`scripts/known-hashes`).
- Change nothing under the installed copy (`factory/`, `.claude/` at the repo root); only `vendor/factory/` and plugin files.
- Old configs must keep working: read `digest` with defaults (`CONFIG.get("digest") or {}`). `/factory-update` adds the new key to installed configs.
- Full check: `scripts/check`. One test file: `python3 -m unittest tests/<file>.py -v`.
- This plan is built after Phase 2 (`scripts/e2e`) is merged. Task 7 extends its scenarios. If `scripts/e2e` isn't on the base branch, record Task 7 under `## Deviations` and skip it.
- The dashboard already polls every 2 s and shows the update time, which more than covers the spec's 30 s refresh. This plan adds the pause toggle and the strip.

## File map

| File | Change |
|---|---|
| `vendor/factory/factory/bin/job` | `report_data`, `report_md`, `cmd_report`, `cmd_digest`, usage lines, `main` dispatch |
| `vendor/factory/factory/config.json` | `"digest": {"enabled": true, "hour": 9, "days": 1}`, `labels.digest` |
| `vendor/factory/factory/bin/doctor` | `factory:digest` in `LABELS`; `digest` validation in `check_config` |
| `vendor/factory/factory/bin/runner` | `chores()` after the pull |
| `vendor/factory/.claude/skills/factory/SKILL.md` | `/factory report`; run step 5 runs report and digest |
| `vendor/factory/factory/dashboard.html` | summary strip, pause toggle, tolerant `loadJobs` |
| `skills/factory-install/SKILL.md`, `skills/factory-uninstall/SKILL.md` | create / delete `factory:digest` |
| `tests/installed_project.py` | `factory:digest` in `LABELS` |
| `tests/test_report.py`, `tests/test_digest.py`, `tests/test_dashboard.py` | new |
| `tests/test_doctor.py`, `tests/test_runner.py`, `tests/test_factory_uninstall_skill.py` | extended |
| `README.md` | "What needs me?" and the digest |
| `tests/e2e/report/scenario.json`, `tests/test_e2e_scenarios.py` | e2e scenario |

---

### Task 1: `job report`

**Files:**
- Modify: `vendor/factory/factory/bin/job`
- Create: `tests/test_report.py`

The report reads `job.json` files directly (like `read_jobs`), never through `load()`, so it takes no job lock.

`report_data(days)` returns (keys are stable; `--json` prints exactly this):

```
{"days": 7, "generated": "<iso>", "unreadable": 0,
 "spend": {"total": 0.0, "by_day": {"YYYY-MM-DD": usd, ...}, "top_jobs": [{"id": ..., "usd": ...}],
           "learner": 0.0, "daily_cap": 100 | null, "today": 0.0},
 "throughput": {"by_stage": {"merged": n, "rejected": n, "needs-human": n, "needs-info": n, "in progress": n},
                "rounds_median": x | null, "rounds_max": n | null, "hours_to_merge_median": x | null},
 "attention": [{"id", "issue", "pr", "stage", "waiting_hours", "reason"}],
 "escalations": [{"why": ..., "count": n}],
 "findings": [{"tag": ..., "count": n}],
 "gate": {"first_try_pass": n, "total": n, "rate": x | null}}
```

- A job is **in the window** when it started in the last `days` days, or hasn't ended, or ended in the window.
- **Spend** sums `delta_usd` from log lines in the window: `by_day` has one key per day (UTC dates, oldest first, every day present), `top_jobs` the 5 largest, `learner` from `jobs/learning/log.jsonl`. `today` is `daily_spend()` and `daily_cap` is `budgets()["daily_usd"]`.
- **Attention** lists every job now in `needs-human` or `needs-info`, in the window or not, oldest wait first. `waiting_hours` counts since `ended`. `reason` is the first non-blank line of `decision.md`'s `## Why` (needs-human) or of `intake.md`'s `## Questions` (needs-info), else `-`.
- **Escalations:** window jobs whose `decision.md` starts `ESCALATE`, grouped by the normalised first line of `## Why` (lowercased, digits removed, whitespace collapsed); top 5, most first.
- **Findings:** tags of the findings in each window job's current round (`round-<round>/review-*.md`), via `findings` and `parse_finding`; untagged ones count as `untagged`. Top 10.
- **Gate:** window jobs with `round-1/checks.md`; `first_try_pass` counts those starting `GATE: PASS`.

- [ ] **Step 1: Write the failing tests.** `tests/test_report.py`:

```python
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from factory_project import FactoryProject


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class ReportCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        self.job = self.project.load_job()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)

    def add_job(self, job_id, stage, started_hours_ago=1, ended_hours_ago=None, round_=1, pr=None,
                spend=(), files=None):
        d = self.job.JOBS / job_id
        d.mkdir(parents=True)
        ended = iso(self.now - timedelta(hours=ended_hours_ago)) if ended_hours_ago is not None else None
        (d / "job.json").write_text(json.dumps({
            "id": job_id, "issue": int(job_id[:3]), "stage": stage, "round": round_, "pr": pr,
            "cost_usd": sum(u for _, u in spend), "started": iso(self.now - timedelta(hours=started_hours_ago)),
            "ended": ended}))
        with (d / "log.jsonl").open("w") as f:
            for hours_ago, usd in spend:
                f.write(json.dumps({"t": iso(self.now - timedelta(hours=hours_ago)), "event": "job",
                                    "stage": stage, "round": round_, "cost_usd": usd, "delta_usd": usd}) + "\n")
        for rel, text in (files or {}).items():
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text(text)

    def report(self, days=7):
        return self.job.report_data(days)


ESCALATED = "ESCALATE\n\n## Why\nThe branch conflicts with main in 3 files.\n"
REVIEW = "VERDICT: CHANGES\n\n## Findings\n1. [missing-test] a.py:1 add one\n2. no tag\n"


class ReportDataTest(ReportCase):
    def test_spend_by_day_top_jobs_and_learner(self):
        self.add_job("001-a", "merged", 50, 49, spend=((50, 2.0), (2, 1.0)))
        self.add_job("002-b", "build", 3, spend=((3, 4.0),))
        self.add_job("003-old", "merged", 24 * 30, 24 * 29, spend=((24 * 30, 9.0),))
        learning = self.job.JOBS / "learning"
        learning.mkdir()
        (learning / "log.jsonl").write_text(json.dumps({"t": iso(self.now), "event": "learn-file", "stage": "learning",
                                                       "round": 0, "cost_usd": 0.5, "delta_usd": 0.5}) + "\n")
        spend = self.report()["spend"]
        self.assertEqual(spend["total"], 7.0)
        self.assertEqual(spend["learner"], 0.5)
        self.assertEqual([j["id"] for j in spend["top_jobs"]], ["002-b", "001-a"])
        self.assertEqual(len(spend["by_day"]), 7)
        self.assertEqual(sum(spend["by_day"].values()), 7.0)
        self.assertEqual(spend["daily_cap"], self.job.budgets()["daily_usd"])

    def test_throughput_rounds_and_hours(self):
        self.add_job("001-a", "merged", 10, 6, round_=1)
        self.add_job("002-b", "merged", 10, 2, round_=3)
        self.add_job("003-c", "rejected", 5, 4)
        self.add_job("004-d", "review", 5)
        t = self.report()["throughput"]
        self.assertEqual(t["by_stage"], {"merged": 2, "rejected": 1, "needs-human": 0, "needs-info": 0,
                                         "in progress": 1})
        self.assertEqual((t["rounds_median"], t["rounds_max"]), (2, 3))
        self.assertEqual(t["hours_to_merge_median"], 6.0)

    def test_attention_lists_waiting_jobs_oldest_first_with_reasons(self):
        self.add_job("001-a", "needs-human", 24 * 40, 30, pr=9, files={"decision.md": ESCALATED})
        self.add_job("002-b", "needs-info", 3, 2, files={"intake.md": "DECISION: NEEDS-INFO\n\n## Questions\n1. Which page size?\n"})
        attention = self.report()["attention"]
        self.assertEqual([a["id"] for a in attention], ["001-a", "002-b"])
        self.assertEqual(attention[0]["reason"], "The branch conflicts with main in 3 files.")
        self.assertEqual(attention[0]["pr"], 9)
        self.assertEqual(attention[1]["reason"], "1. Which page size?")
        self.assertAlmostEqual(attention[0]["waiting_hours"], 30, delta=0.1)

    def test_escalations_group_by_normalised_why(self):
        self.add_job("001-a", "needs-human", 5, 4, files={"decision.md": ESCALATED})
        self.add_job("002-b", "needs-human", 5, 4,
                     files={"decision.md": ESCALATED.replace("3 files", "12   files")})
        self.assertEqual(self.report()["escalations"],
                         [{"why": "the branch conflicts with main in files.", "count": 2}])

    def test_findings_from_the_current_round_and_gate_rate(self):
        self.add_job("001-a", "review", 5, round_=2, files={
            "round-1/review-code.md": REVIEW.replace("missing-test", "dead-code"),
            "round-2/review-code.md": REVIEW,
            "round-1/checks.md": "GATE: FAIL\n"})
        self.add_job("002-b", "merged", 5, 4, files={"round-1/checks.md": "GATE: PASS\n"})
        data = self.report()
        self.assertEqual(data["findings"], [{"tag": "missing-test", "count": 1}, {"tag": "untagged", "count": 1}])
        self.assertEqual(data["gate"], {"first_try_pass": 1, "total": 2, "rate": 0.5})

    def test_an_unreadable_job_is_counted_not_fatal(self):
        bad = self.job.JOBS / "009-bad"
        bad.mkdir(parents=True)
        (bad / "job.json").write_text("{not json")
        self.assertEqual(self.report()["unreadable"], 1)


class ReportCommandTest(ReportCase):
    def run_cmd(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_report(list(args))
        return out.getvalue()

    def test_markdown_has_every_section(self):
        self.add_job("001-a", "needs-human", 5, 4, pr=3, files={"decision.md": ESCALATED})
        text = self.run_cmd("--days", "3")
        for heading in ("## Spend", "## Throughput", "## Needs you", "## Escalations", "## Findings", "## Gate"):
            self.assertIn(heading, text)
        self.assertIn("#1 (needs-human", text)

    def test_json_and_write(self):
        data = json.loads(self.run_cmd("--json", "--write"))
        self.assertEqual(set(data), {"days", "generated", "unreadable", "spend", "throughput", "attention",
                                     "escalations", "findings", "gate"})
        self.assertEqual(json.loads((self.job.JOBS / "report.json").read_text())["days"], 7)

    def test_bad_days_dies(self):
        with self.assertRaises(SystemExit):
            self.run_cmd("--days", "0")
```

- [ ] **Step 2: Run them and see them fail.** `python3 -m unittest tests/test_report.py -v` fails with `AttributeError: ... 'report_data'`.

- [ ] **Step 3: Implement.** In `vendor/factory/factory/bin/job`, add a section before `# ---- Commands ----`:

```python
# ---- Report and digest -----------------------------------------------------

WAITING_REASON = {"needs-human": ("decision.md", "Why"), "needs-info": ("intake.md", "Questions")}


def report_jobs():
    """(jobs, unreadable count), read without locks."""
    jobs, unreadable = [], 0
    for p in sorted(JOBS.iterdir()) if JOBS.exists() else []:
        if not (p / "job.json").exists():
            continue
        try:
            jobs.append(json.loads((p / "job.json").read_text()))
        except (OSError, ValueError):
            unreadable += 1
    return jobs, unreadable


def in_window(job, cutoff):
    ended = job.get("ended")
    return parse_time(job["started"]) >= cutoff or not ended or parse_time(ended) >= cutoff


def first_text_line(text):
    return next((line.strip() for line in (text or "").splitlines() if line.strip()), "-")


def median(values):
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def top(counts, n):
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def report_spend(window, days, cutoff, today):
    by_day = {(today - timedelta(days=k)).isoformat(): 0.0 for k in range(days - 1, -1, -1)}
    per_job = {}
    for j in window:
        for e in read_log(job_dir(j["id"]) / "log.jsonl"):
            t = parse_time(e["t"])
            if t >= cutoff:
                per_job[j["id"]] = per_job.get(j["id"], 0.0) + e["delta_usd"]
                day = t.date().isoformat()
                if day in by_day:
                    by_day[day] += e["delta_usd"]
    learner = sum(e["delta_usd"] for e in read_log(LEARNING / "log.jsonl") if parse_time(e["t"]) >= cutoff)
    return {"total": round(sum(per_job.values()), 2), "by_day": {d: round(u, 2) for d, u in by_day.items()},
            "top_jobs": [{"id": i, "usd": round(u, 2)} for i, u in top(per_job, 5)],
            "learner": round(learner, 2), "daily_cap": budgets()["daily_usd"], "today": round(daily_spend(), 2)}


def report_throughput(window):
    by_stage = {"merged": 0, "rejected": 0, "needs-human": 0, "needs-info": 0, "in progress": 0}
    for j in window:
        by_stage[j["stage"] if j["stage"] in by_stage else "in progress"] += 1
    merged = [j for j in window if j["stage"] == "merged" and j.get("ended")]
    rounds = [j["round"] for j in merged]
    hours = [(parse_time(j["ended"]) - parse_time(j["started"])).total_seconds() / 3600 for j in merged]
    return {"by_stage": by_stage, "rounds_median": median(rounds), "rounds_max": max(rounds) if rounds else None,
            "hours_to_merge_median": round(median(hours), 1) if hours else None}


def report_attention(jobs, now_dt):
    rows = []
    for j in jobs:
        if j["stage"] not in WAITING_REASON:
            continue
        name, heading = WAITING_REASON[j["stage"]]
        path = job_dir(j["id"]) / name
        reason = first_text_line(section(path, heading)) if path.exists() else "-"
        since = parse_time(j.get("ended") or j["started"])
        rows.append({"id": j["id"], "issue": j["issue"], "pr": j.get("pr"), "stage": j["stage"],
                     "waiting_hours": round((now_dt - since).total_seconds() / 3600, 1), "reason": reason})
    return sorted(rows, key=lambda r: -r["waiting_hours"])


def report_escalations(window):
    counts = {}
    for j in window:
        path = job_dir(j["id"]) / "decision.md"
        if first_line(path) != "ESCALATE":
            continue
        why = re.sub(r"\s+", " ", re.sub(r"\d+", "", first_text_line(section(path, "Why")).lower())).strip()
        counts[why] = counts.get(why, 0) + 1
    return [{"why": w, "count": c} for w, c in top(counts, 5)]


def report_findings(window):
    counts = {}
    for j in window:
        for path in sorted(round_dir(j).glob("review-*.md")) if j["round"] else []:
            for text in findings(path):
                tag = parse_finding(text)[0] or "untagged"
                counts[tag] = counts.get(tag, 0) + 1
    return [{"tag": t, "count": c} for t, c in top(counts, 10)]


def report_gate(window):
    firsts = [first_line(round_dir(j, 1) / "checks.md") for j in window
              if (round_dir(j, 1) / "checks.md").exists()]
    passed = sum(1 for line in firsts if line == "GATE: PASS")
    return {"first_try_pass": passed, "total": len(firsts),
            "rate": round(passed / len(firsts), 2) if firsts else None}


def report_data(days):
    now_dt = datetime.now(timezone.utc)
    cutoff = now_dt - timedelta(days=days)
    jobs, unreadable = report_jobs()
    window = [j for j in jobs if in_window(j, cutoff)]
    return {"days": days, "generated": now(), "unreadable": unreadable,
            "spend": report_spend(window, days, cutoff, now_dt.date()),
            "throughput": report_throughput(window), "attention": report_attention(jobs, now_dt),
            "escalations": report_escalations(window), "findings": report_findings(window),
            "gate": report_gate(window)}


def waited(hours):
    return f"{hours:.0f}h" if hours < 24 else f"{hours / 24:.0f}d"


def needs_you_line(data):
    items = [f"#{a['issue']} ({a['stage']}, {waited(a['waiting_hours'])})" for a in data["attention"]]
    return "Needs you: " + (", ".join(items) or "nothing")


def money(usd):
    return "-" if usd is None else f"${usd:.2f}"


def report_md(data):
    s, t, g = data["spend"], data["throughput"], data["gate"]
    lines = [needs_you_line(data), "", f"Factory report, last {data['days']} days ({data['generated']})", "",
             "## Spend", "",
             f"- Total {money(s['total'])}, learner {money(s['learner'])}; "
             f"last 24 h {money(s['today'])} of {money(s['daily_cap'])}",
             "- By day: " + ", ".join(f"{d[5:]} {money(u)}" for d, u in s["by_day"].items()),
             "- Top jobs: " + (", ".join(f"{j['id']} {money(j['usd'])}" for j in s["top_jobs"]) or "none"),
             "", "## Throughput", "",
             "- " + ", ".join(f"{k} {v}" for k, v in t["by_stage"].items()),
             f"- Rounds per merged job: median {t['rounds_median'] or '-'}, max {t['rounds_max'] or '-'}",
             f"- Hours from intake to merge (median): {t['hours_to_merge_median'] or '-'}",
             "", "## Needs you", ""]
    lines += [f"- #{a['issue']} ({a['stage']}, {waited(a['waiting_hours'])})"
              + (f" PR #{a['pr']}" if a["pr"] else "") + f": {a['reason']}" for a in data["attention"]] or ["- nothing"]
    lines += ["", "## Escalations", ""]
    lines += [f"- {e['count']} × {e['why']}" for e in data["escalations"]] or ["- none"]
    lines += ["", "## Findings", ""]
    lines += [f"- {f['tag']}: {f['count']}" for f in data["findings"]] or ["- none"]
    lines += ["", "## Gate", "",
              f"- First-try pass: {g['first_try_pass']} of {g['total']}"
              + (f" ({g['rate']:.0%})" if g["rate"] is not None else "")]
    if data["unreadable"]:
        lines += ["", f"{data['unreadable']} job folder(s) couldn't be read."]
    return "\n".join(lines) + "\n"


def write_report(data):
    JOBS.mkdir(parents=True, exist_ok=True)
    tmp = JOBS / "report.json.tmp"
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(JOBS / "report.json")


def cmd_report(args):
    days, as_json, write = 7, False, False
    rest = list(args)
    while rest:
        arg = rest.pop(0)
        if arg == "--days" and rest and rest[0].isdigit() and int(rest[0]) > 0:
            days = int(rest.pop(0))
        elif arg == "--json":
            as_json = True
        elif arg == "--write":
            write = True
        else:
            die(f"bad report arguments: {' '.join(args)} (use --days N with N ≥ 1, --json, --write)")
    data = report_data(days)
    if write:
        write_report(data)
    print(json.dumps(data, indent=2) if as_json else report_md(data), end="" if not as_json else "\n")
```

In the module docstring's usage list, after the `job costs` line, add:

```
  job report [--days N] [--json] [--write]   spend, throughput, what needs you, findings; --write → jobs/report.json
```

In `main`, before the final `else:`, add:

```python
        elif cmd == "report":
            cmd_report(args)
```

- [ ] **Step 4: Run the tests and see them pass.** `python3 -m unittest tests/test_report.py -v`

- [ ] **Step 5: Commit the vendored edit, then the tests.**

```bash
git add vendor/factory/factory/bin/job
git commit -m "feat(vendor): job report summarises spend, throughput and what needs you"
scripts/known-hashes
git add tests/test_report.py vendor/known-hashes.json
git commit -m "test: job report; refresh known hashes"
```

---

### Task 2: `job digest` and its config

**Files:**
- Modify: `vendor/factory/factory/bin/job`, `vendor/factory/factory/config.json`
- Create: `tests/test_digest.py`

Behaviour of `job digest`:
1. `digest.enabled` false → print `DIGEST: off`, exit 0.
2. Local hour (`datetime.now().hour`) below `digest.hour` → `DIGEST: not yet (after <hour>:00)`.
3. `factory/jobs/digest.json` `posted` within the last 20 h → `DIGEST: already posted at <time>`.
4. Find the issue: `gh issue list --label <labels.digest> --state all --limit 20 --json number,state`. Prefer an open one (lowest number), else reopen the lowest closed one (`gh issue reopen`). With none, make sure the label exists (`gh label create <label> --color 0E8A16 --description "Daily factory digest" --force`), create the issue (`gh issue create --title "Factory digest" --label <label> --body "The factory posts a daily summary here."`), and pin it (`gh issue pin <n>`, failure ignored).
5. Comment `<!-- factory -->\n` + `report_md(report_data(days))` on it, then write `digest.json` `{"posted": now(), "issue": n}` via a temp file and print `DIGEST: posted on #<n>`.
6. Any `Refused` from `gh` → print `NOTE: digest not posted: <first line>`, exit 0, `digest.json` untouched (retried next time).

- [ ] **Step 1: Write the failing tests.** `tests/test_digest.py`:

```python
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from factory_project import FactoryProject


class DigestTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        self.job = self.project.load_job()
        self.job.CONFIG["digest"] = {"enabled": True, "hour": 0, "days": 1}
        self.issues = []
        self.calls = []
        self.fail_on = None

        def fake_gh(*args):
            self.calls.append(args)
            if self.fail_on and args[:2] == self.fail_on:
                raise self.job.Refused("gh: boom")
            if args[:2] == ("issue", "list"):
                return json.dumps(self.issues)
            if args[:2] == ("issue", "create"):
                return "https://github.com/o/r/issues/31\n"
            return ""

        self.job.gh = fake_gh

    def digest(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_digest()
        return out.getvalue()

    def state(self):
        path = self.job.JOBS / "digest.json"
        return json.loads(path.read_text()) if path.exists() else None

    def test_creates_labels_and_pins_a_new_digest_issue(self):
        out = self.digest()
        self.assertIn("DIGEST: posted on #31", out)
        kinds = [c[:2] for c in self.calls]
        self.assertIn(("label", "create"), kinds)
        self.assertIn(("issue", "pin"), kinds)
        body = next(c for c in self.calls if c[:2] == ("issue", "comment"))
        self.assertEqual(body[2], "31")
        self.assertIn("Needs you: nothing", body[body.index("--body") + 1])
        self.assertEqual(self.state()["issue"], 31)

    def test_reuses_an_open_issue_and_reopens_a_closed_one(self):
        self.issues = [{"number": 5, "state": "CLOSED"}, {"number": 8, "state": "OPEN"}]
        self.digest()
        self.assertNotIn(("issue", "create"), [c[:2] for c in self.calls])
        self.assertEqual(next(c for c in self.calls if c[:2] == ("issue", "comment"))[2], "8")
        (self.job.JOBS / "digest.json").unlink()
        self.calls.clear()
        self.issues = [{"number": 5, "state": "CLOSED"}]
        self.digest()
        self.assertIn(("issue", "reopen", "5"), self.calls)

    def test_waits_for_the_hour_and_twenty_hours(self):
        self.job.CONFIG["digest"]["hour"] = 24  # never reached
        self.assertIn("DIGEST: not yet", self.digest())
        self.job.CONFIG["digest"]["hour"] = 0
        self.job.JOBS.mkdir(parents=True, exist_ok=True)
        recent = (datetime.now(timezone.utc) - timedelta(hours=19)).strftime("%Y-%m-%dT%H:%M:%SZ")
        (self.job.JOBS / "digest.json").write_text(json.dumps({"posted": recent, "issue": 3}))
        self.assertIn("DIGEST: already posted", self.digest())
        self.assertEqual(self.calls, [])

    def test_off_when_disabled_and_defaults_when_missing(self):
        self.job.CONFIG["digest"]["enabled"] = False
        self.assertIn("DIGEST: off", self.digest())
        del self.job.CONFIG["digest"]
        self.assertEqual(self.job.digest_config(), {"enabled": True, "hour": 9, "days": 1})

    def test_gh_failure_is_a_note_and_records_nothing(self):
        self.fail_on = ("issue", "comment")
        out = self.digest()
        self.assertIn("NOTE: digest not posted", out)
        self.assertIsNone(self.state())

    def test_the_line_lists_waiting_jobs(self):
        d = self.job.JOBS / "012-x"
        d.mkdir(parents=True)
        ended = (datetime.now(timezone.utc) - timedelta(hours=50)).strftime("%Y-%m-%dT%H:%M:%SZ")
        (d / "job.json").write_text(json.dumps({"id": "012-x", "issue": 12, "stage": "needs-human", "round": 1,
                                                "pr": 4, "cost_usd": 0, "started": ended, "ended": ended}))
        self.assertEqual(self.job.needs_you_line(self.job.report_data(1)), "Needs you: #12 (needs-human, 2d)")
```

- [ ] **Step 2: Run them and see them fail** with `AttributeError` (no `cmd_digest`).

- [ ] **Step 3: Implement.** In `vendor/factory/factory/config.json`, add after the `learning` object:

```json
  "digest": { "enabled": true, "hour": 9, "days": 1 },
```

and in `labels` add `"digest": "factory:digest"` after `"learning"`. Then, in `job`, after `cmd_report`:

```python
DIGEST_DEFAULTS = {"enabled": True, "hour": 9, "days": 1}
DIGEST_EVERY_HOURS = 20


def digest_config():
    return {**DIGEST_DEFAULTS, **(CONFIG.get("digest") or {})}


def digest_label():
    return LABELS.get("digest", "factory:digest")


def digest_issue():
    """The digest issue's number: an open one, else a reopened closed one, else a new pinned one."""
    label_name = digest_label()
    issues = sorted(gh_json("issue", "list", "--label", label_name, "--state", "all", "--limit", "20",
                            "--json", "number,state"), key=lambda i: i["number"])
    open_ones = [i for i in issues if i["state"] == "OPEN"]
    if open_ones:
        return open_ones[0]["number"]
    if issues:
        gh("issue", "reopen", str(issues[0]["number"]))
        return issues[0]["number"]
    gh("label", "create", label_name, "--color", "0E8A16", "--description", "Daily factory digest", "--force")
    url = gh("issue", "create", "--title", "Factory digest", "--label", label_name,
             "--body", "The factory posts a daily summary here.").strip()
    m = re.search(r"/issues/(\d+)$", url)
    if not m:
        raise Refused(f"gh issue create printed {url!r}, not an issue URL")
    number = int(m.group(1))
    try:
        gh("issue", "pin", str(number))
    except Refused:
        pass  # pinning is a convenience; the label finds the issue
    return number


def cmd_digest():
    cfg = digest_config()
    if not cfg["enabled"]:
        print("DIGEST: off")
        return
    if datetime.now().hour < cfg["hour"]:
        print(f"DIGEST: not yet (after {cfg['hour']}:00)")
        return
    path = JOBS / "digest.json"
    last = json.loads(path.read_text()) if path.exists() else {}
    if last.get("posted") and datetime.now(timezone.utc) - parse_time(last["posted"]) < timedelta(hours=DIGEST_EVERY_HOURS):
        print(f"DIGEST: already posted at {last['posted']}")
        return
    try:
        number = digest_issue()
        gh("issue", "comment", str(number), "--body", f"{MARKER}\n{report_md(report_data(cfg['days']))}")
    except Refused as e:
        print(f"NOTE: digest not posted: {str(e).splitlines()[0]}")
        return
    JOBS.mkdir(parents=True, exist_ok=True)
    tmp = JOBS / "digest.json.tmp"
    tmp.write_text(json.dumps({"posted": now(), "issue": number}) + "\n")
    tmp.replace(path)
    print(f"DIGEST: posted on #{number}")
```

Usage line after the `job report` line:

```
  job digest                     post the report on the factory:digest issue, once a day after digest.hour
```

`main`, before the final `else:`:

```python
        elif cmd == "digest" and not args:
            cmd_digest()
```

- [ ] **Step 4: Run the tests and see them pass.** `python3 -m unittest tests/test_digest.py tests/test_report.py -v`, then `scripts/check --fast` (the config check must still pass).

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/factory/bin/job vendor/factory/factory/config.json
git commit -m "feat(vendor): job digest posts the report on a pinned digest issue daily"
scripts/known-hashes
git add tests/test_digest.py vendor/known-hashes.json
git commit -m "test: job digest; refresh known hashes"
```

---

### Task 3: Doctor, labels and the install skills

**Files:**
- Modify: `vendor/factory/factory/bin/doctor`, `skills/factory-install/SKILL.md`, `skills/factory-uninstall/SKILL.md`, `tests/installed_project.py`, `tests/test_doctor.py`, `tests/test_factory_uninstall_skill.py`

- [ ] **Step 1: Write the failing tests.** In `tests/installed_project.py`, change `LABELS` to:

```python
LABELS = ("factory", "factory:needs-info", "factory:needs-human", "factory:planned",
          "factory:learning", "factory:digest")
```

Append to the class in `tests/test_doctor.py` that holds `test_missing_learning_label_fails` (it has `self.p` and `assertFails`):

```python
    def test_missing_digest_label_fails(self):
        self.p.set_labels([name for name in LABELS if name != "factory:digest"])
        self.assertFails("labels", "label 'factory:digest' missing")

    def test_bad_digest_config_fails(self):
        cfg = json.loads((self.p.root / "factory/config.json").read_text())
        cfg["digest"] = {"enabled": "yes", "hour": 24, "days": 0}
        self.p.write("factory/config.json", json.dumps(cfg))
        res = self.p.run("doctor", "--fast")
        for text in ("digest.enabled must be true or false", "digest.hour must be an integer from 0 to 23",
                     "digest.days must be a positive integer"):
            self.assertIn(text, res.stdout)

    def test_missing_digest_config_is_fine(self):
        cfg = json.loads((self.p.root / "factory/config.json").read_text())
        cfg.pop("digest")
        self.p.write("factory/config.json", json.dumps(cfg))
        self.assertNotIn("digest", self.p.run("doctor", "--fast").stdout)
```

(If `json` isn't imported in `tests/test_doctor.py`, import it.) In `tests/test_factory_uninstall_skill.py`, add to its test class:

```python
    def test_deletes_the_digest_label(self):
        text = (PLUGIN / "skills" / "factory-uninstall" / "SKILL.md").read_text()
        self.assertIn("gh label delete factory:digest --yes", text)
```

(using that file's existing path constant for the plugin root; add `PLUGIN = Path(__file__).resolve().parents[1]` if it has none). Add a test that the install skill creates the label, in the same file or `tests/test_handoff_skill.py`'s style:

```python
    def test_install_creates_the_digest_label(self):
        text = (PLUGIN / "skills" / "factory-install" / "SKILL.md").read_text()
        self.assertIn("gh label create factory:digest", text)
```

- [ ] **Step 2: Run them and see them fail.** `python3 -m unittest tests/test_doctor.py tests/test_factory_uninstall_skill.py -v`

- [ ] **Step 3: Implement doctor.** In `vendor/factory/factory/bin/doctor`, add `"factory:digest"` to `LABELS`:

```python
LABELS = ("factory", "factory:needs-info", "factory:needs-human", "factory:planned",
          "factory:learning", "factory:digest")
```

and in `check_config`, before `if not isinstance(cfg.get("agents", {}).get("learner"), dict):`:

```python
    digest = cfg.get("digest")
    if digest is not None:
        if not isinstance(digest, dict):
            problems.append(fail("digest must be an object with enabled, hour and days"))
        else:
            if not isinstance(digest.get("enabled", True), bool):
                problems.append(fail("digest.enabled must be true or false"))
            hour = digest.get("hour", 9)
            if isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23:
                problems.append(fail("digest.hour must be an integer from 0 to 23"))
            days = digest.get("days", 1)
            if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
                problems.append(fail("digest.days must be a positive integer"))
```

- [ ] **Step 4: The skills.** In `skills/factory-install/SKILL.md`, **Step 2 (Adapt), labels**, change the sentence to "also create the planned, learning and digest labels:" and add to the code block:

```bash
gh label create factory:digest --color 0E8A16 --description "Daily factory digest"
```

In `skills/factory-uninstall/SKILL.md`, after `gh label delete factory:learning --yes`, add:

```bash
    gh label delete factory:digest --yes
```

- [ ] **Step 5: Run the tests and see them pass**, then `scripts/check`.

- [ ] **Step 6: Commit.**

```bash
git add vendor/factory/factory/bin/doctor
git commit -m "feat(vendor): doctor checks the digest label and config"
scripts/known-hashes
git add skills/factory-install/SKILL.md skills/factory-uninstall/SKILL.md tests/installed_project.py \
  tests/test_doctor.py tests/test_factory_uninstall_skill.py vendor/known-hashes.json
git commit -m "feat: install and uninstall the digest label; refresh known hashes"
```

---

### Task 4: The runner runs the report and digest every tick

**Files:**
- Modify: `vendor/factory/factory/bin/runner`, `tests/test_runner.py`

Every tick that passes the pull runs `job report --write` and then `job digest`, each with a 120 s timeout, before `has_work()`. Their output isn't logged, so a tick still logs exactly one line. A failure here never fails the tick.

- [ ] **Step 1: Write the failing test.** Append to `TickTest` in `tests/test_runner.py`:

```python
    def test_tick_writes_the_report_even_when_idle(self):
        res = self.runner("tick")
        self.assertEqual(res.returncode, 0, res.stderr)
        report = json.loads((self.p.root / "factory/jobs/report.json").read_text())
        self.assertEqual(report["days"], 7)
        self.assertEqual(len(self.log_lines()), 1)
```

- [ ] **Step 2: Run it and see it fail** (no `report.json`): `python3 -m unittest tests/test_runner.py -k report -v`

- [ ] **Step 3: Implement.** In `vendor/factory/factory/bin/runner`, add before `cmd_tick`:

```python
CHORE_SECONDS = 120


def chores():
    """Report and digest: no Claude session, so they run every tick. Their failures never fail the tick."""
    for args in (["report", "--write"], ["digest"]):
        try:
            subprocess.run([sys.executable, str(FACTORY / "bin" / "job"), *args], cwd=REPO,
                           capture_output=True, text=True, timeout=CHORE_SECONDS)
        except (OSError, subprocess.TimeoutExpired):
            pass  # the next tick tries again
```

In `cmd_tick`, right after the block that logs `skipped: pull failed` and returns, before `try:` / `work = has_work()`, add:

```python
    chores()
```

In the module docstring, change the `runner tick` line to:

```
  runner tick                  one scheduled run: lock, preflight, pull, report and digest, check the queue, run /factory run headless
```

- [ ] **Step 4: Run the runner tests and see them pass.** `python3 -m unittest tests/test_runner.py -v`

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/factory/bin/runner
git commit -m "feat(vendor): runner writes the report and posts the digest every tick"
scripts/known-hashes
git add tests/test_runner.py vendor/known-hashes.json
git commit -m "test: runner tick writes the report; refresh known hashes"
```

---

### Task 5: The orchestrator skill

**Files:**
- Modify: `vendor/factory/.claude/skills/factory/SKILL.md`
- Create: `tests/test_visibility_wording.py`

- [ ] **Step 1: Write the failing test.** `tests/test_visibility_wording.py`:

```python
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "vendor/factory/.claude/skills/factory/SKILL.md"


class SkillWordingTest(unittest.TestCase):
    def test_report_command_and_end_of_run_steps(self):
        text = SKILL.read_text()
        self.assertIn("/factory report", text)
        self.assertIn("factory/bin/job report --write", text)
        self.assertIn("factory/bin/job digest", text)
```

- [ ] **Step 2: Run it and see it fail.** `python3 -m unittest tests/test_visibility_wording.py -v`

- [ ] **Step 3: Edit the skill.** In the command block near the top, after the `/factory run <n>` line, add:

```
/factory report       print factory/bin/job report; posts nothing
```

In **/factory run**, at the end of step 5 add:

```markdown
   Then run `factory/bin/job report --write` (it refreshes the dashboard's
   strip) and `factory/bin/job digest`, and report its `DIGEST:` or `NOTE:`
   line.
```

After the **/factory run <n>** section, add:

```markdown
## /factory report

Run `factory/bin/job report` (add `--days <n>` when the user names a
period) and show its output as it is. It posts nothing and changes nothing.
```

In **/factory <anything>**, in the **What needs them** bullet, add at the end: "The digest issue (label `factory:digest`) has the same list each day."

- [ ] **Step 4: Run it and see it pass.**

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/.claude/skills/factory/SKILL.md
git commit -m "feat(vendor): /factory report, and runs end with the report and digest"
scripts/known-hashes
git add tests/test_visibility_wording.py vendor/known-hashes.json
git commit -m "test: factory skill report and digest wording; refresh known hashes"
```

---

### Task 6: Dashboard strip and pause

**Files:**
- Modify: `vendor/factory/factory/dashboard.html`
- Create: `tests/test_dashboard.py`

- [ ] **Step 1: Write the failing test.** `tests/test_dashboard.py`:

```python
import unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[1] / "vendor/factory/factory/dashboard.html"


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.html = DASHBOARD.read_text()

    def test_summary_strip_reads_report_json_and_hides_without_it(self):
        self.assertIn('id="strip"', self.html)
        self.assertIn("jobs/report.json", self.html)
        self.assertIn("$('strip').hidden = true", self.html)

    def test_pause_toggle(self):
        self.assertIn('id="pause"', self.html)
        self.assertIn("if (paused) return", self.html)

    def test_folders_without_job_json_are_skipped(self):
        self.assertIn(".filter(Boolean)", self.html)
```

- [ ] **Step 2: Run it and see it fail.** `python3 -m unittest tests/test_dashboard.py -v`

- [ ] **Step 3: Edit the dashboard.**

In the `<header>`, after the status div, add:

```html
  <button class="pause" id="pause" type="button" aria-pressed="false">Pause</button>
```

After `<div id="banner"></div>`, add:

```html
<div class="strip" id="strip" hidden></div>
```

In the `<style>` block, after the `.status.error .dot` rule, add:

```css
  .pause { font: inherit; font-size: 12px; margin-left: 12px; padding: 2px 10px; border: 1px solid var(--muted);
           border-radius: 4px; background: none; color: var(--muted); cursor: pointer; }
  .pause[aria-pressed="true"] { color: var(--human); border-color: var(--human); }
  .strip { font-family: var(--mono); font-size: 12px; padding: 6px 16px; color: var(--muted);
           border-bottom: 1px solid rgba(127, 127, 127, 0.2); }
  .strip b { color: inherit; font-weight: 600; }
```

In the script, after `let openText = null`, add:

```javascript
let paused = false

function money(v) { return v == null ? '-' : `$${Number(v).toFixed(2)}` }

// factory/bin/job report --write keeps jobs/report.json current; without it the strip stays hidden.
async function renderStrip() {
  let r
  try { r = JSON.parse(await fetchText('jobs/report.json')) } catch { $('strip').hidden = true; return }
  const top = (r.findings || [])[0]
  const waiting = (r.attention || []).length
  $('strip').innerHTML = [
    `today <b>${money(r.spend?.today)}</b> of ${money(r.spend?.daily_cap)}`,
    `<b>${waiting}</b> need${waiting === 1 ? 's' : ''} you`,
    `<b>${r.throughput?.by_stage?.merged ?? 0}</b> merged in ${r.days} days`,
    top ? `top finding <b>${esc(top.tag)}</b>` : 'no findings',
  ].join(' · ')
  $('strip').hidden = false
}

$('pause').addEventListener('click', () => {
  paused = !paused
  $('pause').setAttribute('aria-pressed', String(paused))
  $('pause').textContent = paused ? 'Resume' : 'Pause'
  if (!paused) poll()
})
```

In `poll()`, make the first line of the function body:

```javascript
  if (paused) return
```

and after `await render()` add `await renderStrip()`.

In `loadJobs()`, replace the last line (`return Promise.all(...)`) with one that skips folders without a readable `job.json` (`learning/`, `runs/`):

```javascript
  const loaded = await Promise.all(ids.map(async (id) => {
    try { return JSON.parse(await fetchText(`jobs/${id}/job.json`)) } catch { return null }
  }))
  return loaded.filter(Boolean)
```

- [ ] **Step 4: Run it and see it pass.** Also open the dashboard once by hand if you can (`cd vendor/factory/factory && python3 -m http.server`); the board and strip must render with and without `jobs/report.json`. If you can't, say so in build.md.

- [ ] **Step 5: Commit.**

```bash
git add vendor/factory/factory/dashboard.html
git commit -m "feat(vendor): dashboard summary strip from report.json and a pause toggle"
scripts/known-hashes
git add tests/test_dashboard.py vendor/known-hashes.json
git commit -m "test: dashboard strip and pause; refresh known hashes"
```

---

### Task 7: README and the e2e scenario

**Files:**
- Modify: `README.md`, `tests/test_e2e_scenarios.py`
- Create: `tests/e2e/report/scenario.json`

- [ ] **Step 1: README.** Under `## Everyday use`, after `### Approving and steering`, add:

```markdown
### What needs me?

The factory comments as you, and GitHub doesn't notify you about your own
comments. So check two places instead:

- **The digest issue.** Once a day after `digest.hour` (local time), the
  factory posts a report on the pinned issue labeled `factory:digest`. Its
  first line lists what needs you, for example
  `Needs you: #12 (needs-human, 2d), #15 (needs-info, 5h)`. A runner posts it
  on its own; without one, the end of each `/factory run` posts it.
- **A saved search.** On your repo's Issues tab, search
  `is:open label:factory:needs-human,factory:needs-info` and save it.

`/factory report` prints the same report (spend, throughput, escalations,
findings, gate pass rate) without posting it, and the dashboard shows a summary
strip from `factory/jobs/report.json`.
```

Under `## Configuration` → `### The basics` (or the closest list of config keys), add:

```markdown
- `digest`: `enabled`, `hour` (local, 0–23) and `days` (the period the
  digest covers). Set `enabled` to `false` to stop posting.
```

- [ ] **Step 2: The scenario.** `tests/e2e/report/scenario.json`:

```json
{
  "config_patch": {"digest": {"enabled": true, "hour": 0, "days": 1}},
  "expect": {"files": ["report.json", "digest.json"]},
  "timeout_minutes": 20
}
```

In `tests/test_e2e_scenarios.py`, add `"report"` to the expected list in `test_every_shipped_scenario_is_valid`, keeping it sorted:

```python
        self.assertEqual(names, ["budget-stop", "happy-path", "learning", "needs-info", "report",
                                 "runner-tick", "tagged-finding"])
```

- [ ] **Step 3: Check.** `scripts/check`

- [ ] **Step 4: Commit.**

```bash
git add README.md tests/e2e/report/scenario.json tests/test_e2e_scenarios.py
git commit -m "docs: what needs me, the digest; e2e report scenario"
```

---

## For the human after merge

- Run `/factory-update` here, then create the label once: `gh label create factory:digest --color 0E8A16 --description "Daily factory digest"` (the digest also creates it on first use).
- Add the `factory` label to the Phase 4 issue.
