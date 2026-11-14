import unittest
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[1] / "vendor/factory/.claude"
AGENTS = Path(__file__).resolve().parents[1] / "vendor/factory/factory/agents"


class PartsWordingTest(unittest.TestCase):
    def test_header_carries_the_range(self):
        self.assertIn("Tasks: <tasks> of <plan_tasks>.", (VENDOR / "skills/factory/SKILL.md").read_text())

    def test_builder_does_only_its_range(self):
        self.assertIn("carry out only the tasks in `Tasks:`", (AGENTS / "builder.md").read_text())

    def test_reviewer_and_approver_judge_the_range(self):
        for name in ("reviewer-code", "approver"):
            self.assertIn("only the tasks in `Tasks:`", (AGENTS / f"{name}.md").read_text(), name)


if __name__ == "__main__":
    unittest.main()
