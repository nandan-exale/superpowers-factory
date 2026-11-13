import contextlib
import io
import json
import unittest

from budget_case import BudgetCase

BODY = ("Part.\n\n```factory-plan\nspec: docs/superpowers/specs/2026-11-12-widget-design.md\n"
        "plan: docs/superpowers/plans/2026-11-12-widget.md\ncommit: {sha}\nrisk: medium\nsurfaces: []\n"
        "part: 2/2\ntasks: 1-1\ndepends: #7\n```\n")


class QueueDependsTest(BudgetCase):
    def setUp(self):
        super().setUp()
        self.dep_state = "OPEN"
        base = self.fake_gh_json

        def gh_json(*args):
            if args[:2] == ("issue", "view"):
                return {"state": self.dep_state}
            return base(*args)

        self.job.gh_json = gh_json
        self.issues = [{"number": 9, "title": "Widget (part 2/2)", "body": BODY.format(sha=self.project.sha),
                        "labels": [{"name": "factory"}, {"name": "factory:planned"}]}]

    def queue(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_queue()
        return [l.split("\t") for l in out.getvalue().splitlines()]

    def row(self, n):
        return next(r for r in self.queue() if r[1] == str(n))

    def test_waits_while_part_one_is_open(self):
        row = self.row(9)
        self.assertEqual((row[0], row[-1]), ("wait", "depends #7"))

    def test_starts_once_part_one_merged(self):
        job = self.job.load(self.job_id)
        job.update(stage="merged")
        self.job.save(job)
        self.dep_state = "CLOSED"
        self.assertEqual(self.row(9)[0], "new")

    def test_a_failed_dependency_starts_so_planned_can_refuse_it(self):
        job = self.job.load(self.job_id)
        job.update(stage="rejected")
        self.job.save(job)
        self.assertEqual(self.job.dependency_state(7, {7: job}), "failed")
        self.assertEqual(self.row(9)[0], "new")

    def test_closed_without_a_merged_job_is_failed(self):
        self.dep_state = "CLOSED"
        self.assertEqual(self.job.dependency_state(7, {}), "failed")


PLAN = "# Widget plan\n\n### Task 1: Spin\n\n### Task 2: Stop\n\n### Task 3: Wobble\n"


class PlannedPartTest(BudgetCase):
    def setUp(self):
        super().setUp()
        repo = self.project.repo
        (repo / "docs/superpowers/plans/2026-11-12-widget.md").write_text(PLAN)
        from factory_project import git
        git(repo, "commit", "-qam", "three tasks")
        git(repo, "push", "-q", "origin", "main")
        self.sha = git(repo, "rev-parse", "HEAD")
        self.dep = {"stage": "merged"}
        self.job.dependency_state = lambda issue, jobs: self.dep["stage"]

    def planned(self, extra):
        body = BODY.format(sha=self.sha).replace("part: 2/2\ntasks: 1-1\ndepends: #7\n", extra)
        self.project.set_issue(body, labels=("factory", "factory:planned"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.job.cmd_planned(self.job.sync(self.job.load(self.job_id)))
        return out.getvalue(), json.loads((self.d / "job.json").read_text())

    def test_records_the_range(self):
        out, job = self.planned("part: 2/2\ntasks: 2-3\ndepends: #5\n")
        self.assertIn("PLANNED:", out)
        self.assertEqual((job["part"], job["tasks"], job["plan_tasks"]), ("2/2", "2-3", 3))
        self.assertIn("build only tasks 2-3 of 3", (self.d / "intake.md").read_text())

    def test_range_past_the_plan_is_refused(self):
        out, job = self.planned("part: 1/2\ntasks: 1-4\n")
        self.assertIn("PLANNED: REFUSED tasks 1-4 is past the plan's 3 tasks", out)
        self.assertEqual(job["stage"], "needs-human")

    def test_failed_dependency_is_refused(self):
        self.dep["stage"] = "failed"
        out, job = self.planned("part: 2/2\ntasks: 2-3\ndepends: #5\n")
        self.assertIn("part 1 (#5) didn't merge; re-plan or remove the dependency", out)
        self.assertEqual(job["stage"], "needs-human")


if __name__ == "__main__":
    unittest.main()
