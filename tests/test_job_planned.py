import os
import tempfile
import unittest

from factory_project import FactoryProject, plan_body


class PlannedTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CLAUDE_CONFIG_DIR"] = self.tmp.name
        self.project = FactoryProject(self.tmp.name)
        self.project.set_issue(plan_body(self.project.sha))
        self.job = self.project.load_job()
        self.job_id = self.project.create_job(self.job)
        self.d = self.job.job_dir(self.job_id)

    def tearDown(self):
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        self.tmp.cleanup()

    def load(self):
        return self.job.sync(self.job.load(self.job_id))


class TransitionTest(PlannedTestCase):
    def test_intake_to_needs_human_requires_decision_md(self):
        with self.assertRaises(self.job.Refused) as ctx:
            self.job.advance(self.load(), "needs-human")
        self.assertIn("only `job planned`", str(ctx.exception))

    def test_intake_to_needs_human_with_decision_md(self):
        job = self.load()
        self.job.escalate(job, "The handoff block was refused: test")
        job = self.job.advance(job, "needs-human")
        self.assertEqual(job["stage"], "needs-human")
        self.assertIn(("issue", "edit", "7", "--add-label", "factory:needs-human"), self.project.gh_calls)

    def test_feedback_refused_when_job_never_built(self):
        job = self.load()
        self.job.escalate(job, "The handoff block was refused: test")
        job = self.job.advance(job, "needs-human")
        (self.d / "feedback-1.md").write_text("# Feedback 1\n\ntry again\n")
        os.utime(self.d / "feedback-1.md", (2_000_000_000, 2_000_000_000))
        with self.assertRaises(self.job.Refused) as ctx:
            self.job.advance(job, "build")
        self.assertIn("never reached build", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
