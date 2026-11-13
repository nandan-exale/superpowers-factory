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
