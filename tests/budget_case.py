"""A FactoryProject job with cost and GitHub faked, for budget and evidence tests."""

import contextlib
import io
import json
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
        self.project = FactoryProject(tmp.name)
        self.project.set_issue("Build the widget.", labels=("factory",))
        self.job = self.project.load_job()
        self.cost = 0.0
        self.job.cost_usd = lambda job: self.cost
        self.issues = []
        self.prs = []
        self.pr_body = ""
        self.edit_error = None
        self.job.gh_json = self.fake_gh_json
        fake_gh = self.job.gh
        self.job.gh = lambda *args: self.fake_gh(fake_gh, *args)
        self.job_id = self.project.create_job(self.job)
        self.d = self.job.job_dir(self.job_id)

    def fake_gh(self, recorder, *args):
        if args[:2] == ("pr", "edit"):
            if self.edit_error:
                raise self.job.Refused(self.edit_error)
            self.pr_body = Path(args[-1]).read_text()
        return recorder(*args)

    def fake_gh_json(self, *args):
        if args[:2] == ("pr", "view"):
            return {"state": "OPEN", "isDraft": False, "body": self.pr_body}
        if args[:2] == ("pr", "list"):
            return list(self.prs)
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
