import sys
import unittest
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[1] / "vendor/factory/factory/agents"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor/factory/factory/lib"))

from orchestrator import prompts  # noqa: E402


class PartsWordingTest(unittest.TestCase):
    def test_header_carries_the_range(self):
        job = {"id": "004-x", "worktree": "/w", "branch": "b", "issue": 1, "tasks": "4-7", "plan_tasks": 12}
        self.assertTrue(prompts.header(Path("/r"), job, "main").endswith(" Tasks: 4-7 of 12."))

    def test_builder_does_only_its_range(self):
        self.assertIn("carry out only the tasks in `Tasks:`", (AGENTS / "builder.md").read_text())

    def test_reviewer_and_approver_judge_the_range(self):
        for name in ("reviewer-code", "approver"):
            self.assertIn("only the tasks in `Tasks:`", (AGENTS / f"{name}.md").read_text(), name)


if __name__ == "__main__":
    unittest.main()
