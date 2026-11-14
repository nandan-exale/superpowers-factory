import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from budget_case import BudgetCase  # noqa: E402


class RunCapsTest(BudgetCase):
    def setUp(self):
        super().setUp()
        self.job.runtime_caps = lambda: {"reports_cost": False, "reports_tokens": False}
        self.job.CONFIG["budgets"].update(job_runs=3, daily_runs=5)

    def runs(self, n, folder=None):
        d = (folder or self.d) / "runs"
        d.mkdir(exist_ok=True)
        start = len(list(d.glob("[0-9][0-9][0-9]-*.json")))
        for k in range(start + 1, start + n + 1):
            (d / f"{k:03d}-builder.json").write_text(json.dumps({"cost_usd": None, "ended": self.job.now()}))

    def test_job_runs_cap_stops_the_job(self):
        self.in_review()
        self.runs(4)
        job = self.advance("approve")
        self.assertEqual(job["stage"], "needs-human")
        self.assertIn("budget: 4 of 3 agent runs used", job["budget_stopped"])

    def test_feedback_gives_a_fresh_run_allowance(self):
        self.in_review(budget_base_runs=4)
        self.runs(5)
        self.assertEqual(self.advance("approve")["stage"], "approve")

    def test_daily_runs_cap_refuses_new_work(self):
        self.in_review()
        self.runs(6)
        with self.assertRaises(self.job.Refused) as e:
            self.advance("approve")
        self.assertIn("daily budget: 6 of 5 agent runs in the last 24 h", str(e.exception))

    def test_tokens_without_prices_still_count_runs(self):
        self.job.runtime_caps = lambda: {"reports_cost": False, "reports_tokens": True}
        self.job.runtime_config = lambda: {"prices_usd_per_mtok": {}}
        self.in_review()
        self.runs(4)
        self.assertEqual(self.advance("approve")["stage"], "needs-human")

    def test_tokens_with_prices_use_dollar_budgets(self):
        self.job.runtime_caps = lambda: {"reports_cost": False, "reports_tokens": True}
        self.job.runtime_config = lambda: {"prices_usd_per_mtok": {"m": {"input": 1.0, "output": 1.0}}}
        self.in_review()
        self.runs(6)
        self.assertEqual(self.advance("approve")["stage"], "approve")

    def test_caps_are_ignored_when_the_runtime_reports_cost(self):
        self.job.runtime_caps = lambda: {"reports_cost": True, "reports_tokens": True}
        self.in_review()
        self.runs(6)
        self.assertEqual(self.advance("approve")["stage"], "approve")

    def test_cost_cell_says_na_with_the_run_count(self):
        self.in_review()
        self.runs(2)
        self.assertEqual(self.job.cost_cell(self.current()), "n/a (2 runs)")

    def test_summary_total_counts_runs_when_no_cost_is_known(self):
        self.in_review()
        self.runs(2)
        self.assertIn("total n/a (2 agent runs)", self.run_main("summary"))


if __name__ == "__main__":
    unittest.main()
