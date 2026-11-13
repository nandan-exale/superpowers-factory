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
