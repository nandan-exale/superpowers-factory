import contextlib
import io
import os
import tempfile
import unittest

from factory_project import FactoryProject, git, plan_body


class PlannedTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = FactoryProject(self.tmp.name)
        self.project.set_issue(plan_body(self.project.sha))
        self.job = self.project.load_job()
        self.job_id = self.project.create_job(self.job)
        self.d = self.job.job_dir(self.job_id)

    def tearDown(self):
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


class PlannedSuccessTest(PlannedTestCase):
    def test_valid_plan_reaches_build(self):
        self.job.cmd_planned(self.load())
        job = self.load()
        self.assertEqual(job["stage"], "build")
        self.assertEqual(job["round"], 1)
        self.assertTrue(job["planned"])
        self.assertEqual(job["agents"], {
            "spec-writer": {"model": "opus", "effort": "high"},
            "builder": {"model": "opus", "effort": "high"},
            "approver": {"model": "opus", "effort": "high"},
            "reviewers": {"code": {"model": "sonnet", "effort": "high"},
                          "ux": {"model": "sonnet", "effort": "medium"},
                          "ui": {"model": "haiku", "effort": "medium"}},
        })
        self.assertEqual(job["intake"]["decision"], "ACCEPT")
        self.assertEqual(job["intake"]["risk"], "medium")
        self.assertEqual(job["intake"]["surfaces"], ["ui"])

    def test_spec_and_plan_copied_from_commit(self):
        self.job.cmd_planned(self.load())
        self.assertEqual((self.d / "spec.md").read_text(), "# Widget design\n\nThe widget spins.\n")
        self.assertEqual((self.d / "plan.md").read_text(), "# Widget plan\n\n### Task 1: Spin\n")

    def test_worktree_created_and_issue_commented(self):
        self.job.cmd_planned(self.load())
        job = self.load()
        self.assertTrue(os.path.isdir(job["worktree"]))
        comments = [c for c in self.project.gh_calls if c[:2] == ("issue", "comment")]
        self.assertEqual(len(comments), 1)
        self.assertIn("Factory intake: ACCEPT (risk medium, surfaces: ui)", comments[0][4])

    def test_low_risk_no_surfaces_routes_one_reviewer(self):
        self.project.set_issue(plan_body(self.project.sha, risk="low", surfaces="[]"))
        self.job.cmd_planned(self.load())
        self.assertEqual(self.load()["agents"]["reviewers"], {"code": {"model": "haiku", "effort": "medium"}})
        self.assertEqual(self.load()["agents"]["builder"], {"model": "opus", "effort": "medium"})

    def test_planned_job_records_its_spec_and_plan_paths(self):
        self.job.cmd_planned(self.load())
        self.assertEqual(self.load()["plan_paths"],
                         ["docs/superpowers/specs/2026-11-12-widget-design.md",
                          "docs/superpowers/plans/2026-11-12-widget.md"])


class PlannedRefusalTest(PlannedTestCase):
    def assert_refused(self, fragment):
        self.job.cmd_planned(self.load())
        job = self.load()
        self.assertEqual(job["stage"], "needs-human")
        decision = (self.d / "decision.md").read_text()
        self.assertTrue(decision.startswith("ESCALATE\n"))
        self.assertIn(fragment, decision)
        self.assertFalse((self.d / "spec.md").exists())
        self.assertIn(("issue", "edit", "7", "--add-label", "factory:needs-human"), self.project.gh_calls)

    def test_missing_block(self):
        self.project.set_issue("Just build it.")
        self.assert_refused("found 0")

    def test_commit_not_on_base(self):
        self.project.set_issue(plan_body(self.project.unpushed_commit()))
        self.assert_refused("isn't on origin/main")

    def test_unknown_commit(self):
        self.project.set_issue(plan_body("b" * 40))
        self.assert_refused("isn't on origin/main")

    def test_path_missing_at_commit(self):
        self.project.set_issue(plan_body(self.project.sha, plan="docs/superpowers/plans/nope.md"))
        self.assert_refused("doesn't exist at")

    def test_issue_from_another_author(self):
        self.project.set_issue(plan_body(self.project.sha))
        self.project.issue["author"] = {"login": "mallory"}
        self.assert_refused("not @mallory")

    def test_reject_removes_planned_label(self):
        self.project.set_issue("Just build it.")
        self.job.cmd_planned(self.load())
        with contextlib.redirect_stdout(io.StringIO()):
            self.job.cmd_reject(self.load(), "plan was wrong")
        self.assertEqual(self.load()["stage"], "rejected")
        self.assertIn(("issue", "edit", "7", "--remove-label", "factory,factory:needs-human,factory:planned"),
                      self.project.gh_calls)


class PlannedFetchFailureTest(PlannedTestCase):
    def test_fetch_failure_leaves_job_in_intake(self):
        git(self.project.repo, "remote", "set-url", "origin", "/nonexistent/origin.git")
        with self.assertRaises(self.job.Refused):
            self.job.cmd_planned(self.load())
        self.assertEqual(self.load()["stage"], "intake")
        self.assertFalse((self.d / "decision.md").exists())

    def test_operator_lookup_failure_leaves_job_in_intake(self):
        def fail():
            raise self.job.Refused("gh api user failed")
        self.job.operator = fail
        with self.assertRaises(self.job.Refused):
            self.job.cmd_planned(self.load())
        self.assertEqual(self.load()["stage"], "intake")
        self.assertFalse((self.d / "decision.md").exists())


class QueueTest(PlannedTestCase):
    def test_refused_planned_job_hint(self):
        self.project.set_issue("Just build it.")
        self.job.cmd_planned(self.load())
        self.job.gh_json = lambda *a: [{"number": 7, "title": "Build the widget"}]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_queue()
        self.assertIn("reject it, then hand off a fixed plan", out.getvalue())


class PlannedPreconditionTest(PlannedTestCase):
    def test_issue_without_planned_label_exits(self):
        self.project.set_issue(plan_body(self.project.sha), labels=("factory",))
        with self.assertRaises(SystemExit):
            self.job.cmd_planned(self.load())
        self.assertEqual(self.load()["stage"], "intake")

    def test_job_past_intake_exits(self):
        self.job.cmd_planned(self.load())
        with self.assertRaises(SystemExit):
            self.job.cmd_planned(self.load())


if __name__ == "__main__":
    unittest.main()
