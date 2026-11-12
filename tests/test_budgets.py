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


if __name__ == "__main__":
    unittest.main()
