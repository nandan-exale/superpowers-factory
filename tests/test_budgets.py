import unittest

from budget_case import BudgetCase


class LogTest(BudgetCase):
    def test_log_records_only_stage_or_cost_changes(self):
        self.cost = 1.5
        job = self.current()
        self.job.save(job)
        self.job.save(job)
        self.cost = 2.0
        self.job.save(self.current())
        lines = self.log()
        self.assertEqual(len(lines), 3)  # create, 1.5, 2.0
        self.assertAlmostEqual(sum(e["delta_usd"] for e in lines), 2.0)
        self.assertEqual(lines[-1]["cost_usd"], 2.0)
        self.assertEqual(set(lines[-1]), {"t", "event", "stage", "round", "cost_usd", "delta_usd"})

    def test_stage_change_logged_without_cost_change(self):
        job = self.current()
        job["stage"] = "spec"
        self.job.save(job)
        self.assertEqual([e["stage"] for e in self.log()], ["intake", "spec"])

    def test_daily_spend_counts_last_24_hours(self):
        self.spend_elsewhere(10.0, hours_ago=1)
        self.spend_elsewhere(50.0, hours_ago=30)
        self.assertAlmostEqual(self.job.daily_spend(), 10.0)

    def test_bad_log_line_dies(self):
        with (self.d / "log.jsonl").open("a") as f:
            f.write("not json\n")
        with self.assertRaises(SystemExit):
            self.job.daily_spend()


class BudgetConfigTest(BudgetCase):
    def test_invalid_value_dies(self):
        self.job.CONFIG["budgets"]["job_usd"] = "lots"
        with self.assertRaises(SystemExit):
            self.job.budgets()

    def test_missing_budgets_dies(self):
        del self.job.CONFIG["budgets"]
        with self.assertRaises(SystemExit):
            self.job.budgets()

    def test_null_and_numbers_accepted(self):
        self.job.CONFIG["budgets"].update(job_usd=None, job_hours=0.5, daily_usd=100)
        self.assertEqual(self.job.budgets()["job_hours"], 0.5)


class EnforcementTest(BudgetCase):
    def test_over_job_cost_escalates_instead_of_advancing(self):
        self.in_review()
        self.cost = 30.0
        job = self.advance("approve")
        self.assertEqual(job["stage"], "needs-human")
        decision = (self.d / "decision.md").read_text()
        self.assertTrue(decision.startswith("ESCALATE"))
        self.assertIn("budget: $30.00 of $25.00 used", decision)
        bodies = [c[-1] for c in self.gh_calls("pr", "comment")]
        self.assertTrue(any("budget: $30.00 of $25.00 used" in b for b in bodies))

    def test_over_job_time_escalates(self):
        self.in_review(started="2026-01-01T00:00:00Z")
        job = self.advance("approve")
        self.assertEqual(job["stage"], "needs-human")
        self.assertIn("h of 6 h used", (self.d / "decision.md").read_text())

    def test_advance_command_prints_budget_line(self):
        self.in_review()
        self.cost = 30.0
        out = self.run_main("advance", self.job_id, "approve")
        self.assertIn(f"BUDGET: {self.job_id} → needs-human (budget: $30.00 of $25.00 used)", out)

    def test_null_limit_disables_it(self):
        self.job.CONFIG["budgets"]["job_usd"] = None
        self.in_review()
        self.cost = 30.0
        self.assertEqual(self.advance("approve")["stage"], "approve")

    def test_feedback_gives_fresh_allowance(self):
        self.in_review()
        self.cost = 30.0
        self.advance("approve")
        self.job.cmd_feedback(self.job.load(self.job_id), "carry on")
        job = self.current()
        self.assertEqual(job["stage"], "build")
        self.assertEqual(job["budget_base_usd"], 30.0)
        self.assertIsNone(self.job.budget_problem(job))
        self.assertNotIn("budget_stopped", job)

    def test_daily_cap_refuses_and_keeps_stage(self):
        self.in_review()
        self.spend_elsewhere(150.0)
        with self.assertRaises(self.job.Refused) as cm:
            self.job.advance(self.current(), "approve")
        self.assertIn("daily budget: $150.00 of $100.00 in the last 24 h", str(cm.exception))
        self.assertEqual(self.job.load(self.job_id)["stage"], "review")

    def test_spend_older_than_a_day_does_not_count(self):
        self.in_review()
        self.spend_elsewhere(150.0, hours_ago=30)
        self.assertEqual(self.advance("approve")["stage"], "approve")

    def test_queue_waits_when_daily_cap_reached(self):
        self.in_review()
        self.issues = [{"number": 7, "title": "Build the widget"}, {"number": 8, "title": "Other"}]
        self.spend_elsewhere(150.0)
        out = self.run_main("queue")
        rows = [line.split("\t") for line in out.splitlines()]
        actions = {row[1]: (row[0], row[4]) for row in rows}
        self.assertEqual(actions["7"][0], "wait")
        self.assertEqual(actions["8"][0], "wait")
        self.assertIn("daily budget", actions["8"][1])


if __name__ == "__main__":
    unittest.main()
