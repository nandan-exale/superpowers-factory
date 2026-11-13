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
