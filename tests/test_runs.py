import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_project import FactoryProject  # noqa: E402


class RunsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = FactoryProject(tmp.name)
        self.project.set_issue("Build it.", labels=("factory",))
        self.job = self.project.load_job()
        self.job_id = self.project.create_job(self.job)
        self.d = self.job.job_dir(self.job_id)

    def main(self, *argv, stdin=""):
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(stdin)), contextlib.redirect_stdout(out):
            self.job.main(list(argv))
        return out.getvalue()

    def record(self, role, cost, model="claude-opus-5-5"):
        run = {"runtime": "claude", "model": model, "effort": "high", "session_id": "s", "exit": 0,
               "cost_usd": cost, "cost_source": "cli" if cost is not None else None,
               "cost_by_model": {model: cost} if cost is not None else {}}
        return self.main("record-run", self.job_id, role, stdin=json.dumps(run))

    def test_record_run_numbers_files_and_updates_cost(self):
        self.assertIn("runs/001-intake.json", self.record("intake", 1.5))
        self.assertIn("runs/002-builder.json", self.record("builder", 2.25, "claude-sonnet-5-5"))
        saved = json.loads((self.d / "runs" / "002-builder.json").read_text())
        self.assertEqual((saved["seq"], saved["role"], saved["cost_usd"]), (2, "builder", 2.25))
        job = json.loads((self.d / "job.json").read_text())
        self.assertAlmostEqual(job["cost_usd"], 3.75)
        self.assertEqual(self.job.cost_by_model(self.d), {"claude-opus-5-5": 1.5, "claude-sonnet-5-5": 2.25})

    def test_unknown_cost_counts_nothing(self):
        self.record("intake", None)
        self.assertEqual(self.job.cost_for_folder(self.d), 0.0)

    def test_other_files_in_runs_are_not_runs(self):
        (self.d / "runs").mkdir()
        (self.d / "runs" / "20261113T000000000000Z-builder.settings.json").write_text("{}")
        self.assertEqual(self.job.run_files(self.d), [])

    def test_record_run_refuses_bad_stdin(self):
        with self.assertRaises(SystemExit):
            self.main("record-run", self.job_id, "intake", stdin="nope")

    def test_learner_runs_go_to_the_learning_folder(self):
        self.main("record-run", "missing-test", "learner",
                  stdin=json.dumps({"cost_usd": 0.5, "cost_by_model": {"claude-opus-5-5": 0.5}}))
        self.assertTrue((self.job.tag_dir("missing-test") / "runs" / "001-learner.json").exists())
        self.assertEqual(self.job.cost_for_folder(self.job.tag_dir("missing-test")), 0.5)

    def test_set_session_keeps_other_fields(self):
        self.main("set-session", self.job_id, "builder", "abc-123")
        job = json.loads((self.d / "job.json").read_text())
        self.assertEqual(job["sessions"], {"builder": "abc-123"})
        self.assertEqual(job["issue"], 7)

    def test_escalate_works_from_spec(self):
        job = self.job.load(self.job_id)
        self.job.save({**job, "stage": "spec"})
        self.main("escalate", self.job_id, stdin="the spec writer failed twice")
        job = json.loads((self.d / "job.json").read_text())
        self.assertEqual(job["stage"], "needs-human")
        self.assertIn("failed twice", (self.d / "decision.md").read_text())

    def test_escalate_refuses_a_waiting_job(self):
        job = self.job.load(self.job_id)
        self.job.save({**job, "stage": "needs-info"})
        with self.assertRaises(SystemExit):
            self.main("escalate", self.job_id, stdin="x")


if __name__ == "__main__":
    unittest.main()
