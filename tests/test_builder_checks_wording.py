import unittest
from pathlib import Path

BUILDER = Path(__file__).resolve().parents[1] / "vendor/factory/factory/agents/builder.md"


class BuilderChecksWordingTest(unittest.TestCase):
    """The full check suite takes minutes and runs once before the gate anyway; builders that ran it
    after every plan task spent most of each build waiting on it."""

    def setUp(self):
        self.text = " ".join(BUILDER.read_text().split())

    def test_builder_runs_focused_tests_while_working(self):
        self.assertIn("run only the tests that cover what you changed", self.text)

    def test_builder_does_not_run_the_full_suite_itself(self):
        self.assertIn("Don't run the full check suite", self.text)
        self.assertNotIn("Run `bash <main checkout>/factory/checks.sh`", self.text)

    def test_plan_steps_that_run_the_full_suite_are_not_deviations(self):
        self.assertIn("even where the plan says to", self.text)
        self.assertIn("that is not a deviation", self.text)

    def test_verifying_before_ready_uses_focused_tests(self):
        self.assertIn("your evidence is the focused tests", self.text)


if __name__ == "__main__":
    unittest.main()
