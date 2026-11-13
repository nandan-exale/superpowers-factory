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


if __name__ == "__main__":
    unittest.main()
